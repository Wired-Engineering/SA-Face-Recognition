// API service for communicating with Express/FastAPI backend

const BASE_URL = window.location.origin;

class ApiService {
  constructor() {
    this.baseURL = BASE_URL;
    this.credentials = this.getStoredCredentials();
  }

  // Get stored credentials from localStorage
  getStoredCredentials() {
    const stored = localStorage.getItem('adminCredentials');
    return stored ? JSON.parse(stored) : null;
  }

  // Store credentials in localStorage
  storeCredentials(adminId, password) {
    const credentials = { adminId, password };
    localStorage.setItem('adminCredentials', JSON.stringify(credentials));
    this.credentials = credentials;
  }

  // Clear stored credentials
  clearCredentials() {
    localStorage.removeItem('adminCredentials');
    this.credentials = null;
  }

  // Create basic auth header
  getAuthHeader() {
    // Always get fresh credentials from localStorage to avoid stale data
    const credentials = this.getStoredCredentials();
    if (!credentials) return {};
    const encoded = btoa(`${credentials.adminId}:${credentials.password}`);
    return { 'Authorization': `Basic ${encoded}` };
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const defaultOptions = {
      headers: {
        'Content-Type': 'application/json',
      },
    };

    // Add auth headers for protected endpoints (skip for login and public endpoints)
    const isPublicEndpoint = endpoint === '/api/auth/login' ||
                            endpoint === '/api/system/health';

    const authHeaders = !isPublicEndpoint ? this.getAuthHeader() : {};

    // Don't merge headers if options.headers is explicitly empty (for file uploads)
    const config = {
      ...defaultOptions,
      ...options,
      headers: Object.keys(options.headers || {}).length === 0 && options.body instanceof FormData
        ? authHeaders // Only auth headers for FormData uploads
        : {
            ...defaultOptions.headers,
            ...authHeaders,
            ...options.headers,
          },
    };

    try {
      const response = await fetch(url, config);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || `HTTP error! status: ${response.status}`);
      }

      return data;
    } catch (error) {
      console.error(`API Error (${endpoint}):`, error);
      throw error;
    }
  }

  // Authentication methods
  async login(adminId, password) {
    try {
      const result = await this.request('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          admin_id: adminId,
          password: password,
        }),
      });

      // Store credentials on successful login
      if (result.success) {
        this.storeCredentials(adminId, password);
      }

      return result;
    } catch (error) {
      // Clear credentials on login failure
      this.clearCredentials();
      throw error;
    }
  }

  // Logout method
  logout() {
    this.clearCredentials();
  }

  // Check if user is logged in
  isLoggedIn() {
    return this.credentials !== null;
  }

  async changeAdminPassword(oldId, oldPassword, newId, newPassword, confirmPassword) {
    return this.request('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        old_id: oldId,
        old_password: oldPassword,
        new_id: newId,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    });
  }

  // person management methods
  async getpeople() {
    return this.request('/api/people');
  }

  async registerperson(personName, personTitle, personRegistration, imageData) {
    return this.request('/api/people/register', {
      method: 'POST',
      body: JSON.stringify({
        person_name: personName,
        person_title: personTitle,
        person_registration: personRegistration,
        image_data: imageData,
      }),
    });
  }

  async addAdditionalPhoto(personId, imageData) {
    return this.request(`/api/people/${personId}/add-photo`, {
      method: 'POST',
      body: JSON.stringify({
        image_data: imageData,
      }),
    });
  }

  async uploadCSV(file) {
    const formData = new FormData();
    formData.append('file', file);

    return this.request('/api/people/upload-csv', {
      method: 'POST',
      body: formData,
      headers: {}, // Empty headers to let browser set Content-Type with boundary
    });
  }

  uploadCSVStream(file, onProgress, onComplete, onError) {
    // Note: EventSource cannot handle POST requests with file uploads
    // We need to use a different approach: upload file first, then stream progress

    // For now, let's try a hybrid approach: use fetch for the upload with manual SSE parsing
    const formData = new FormData();
    formData.append('file', file);

    // Connect directly to FastAPI server for streaming (bypassing Vite proxy which may not handle SSE properly)
    const streamURL = window.location.hostname === 'localhost'
      ? 'http://localhost:8000/api/people/upload-csv-stream'
      : `${this.baseURL}/api/people/upload-csv-stream`;

    // Get auth headers for streaming request
    const authHeaders = this.getAuthHeader();

    // We need to use fetch to handle file upload with streaming response
    fetch(streamURL, {
      method: 'POST',
      body: formData,
      headers: {
        ...authHeaders,
      },
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const processChunk = ({ done, value }) => {
        if (done) {
          return;
        }

        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;

        // Process complete SSE events (separated by double newline - handle both \r\n\r\n and \n\n)
        const separator = buffer.includes('\r\n\r\n') ? '\r\n\r\n' : '\n\n';

        while (buffer.includes(separator)) {
          const endIndex = buffer.indexOf(separator);
          const eventBlock = buffer.substring(0, endIndex);
          buffer = buffer.substring(endIndex + separator.length);

          if (eventBlock.trim()) {
            this.parseSSEEvent(eventBlock, onProgress, onComplete, onError);
          }
        }

        reader.read().then(processChunk);
      };

      reader.read().then(processChunk);
    })
    .catch(error => {
      onError?.({ error: error.message });
    });
  }

  parseSSEEvent(eventBlock, onProgress, onComplete, onError) {
    // Handle both \r\n and \n line endings
    const lines = eventBlock.split(/\r?\n/);
    let eventType = null;
    let eventData = null;

    lines.forEach(line => {
      const trimmedLine = line.trim();

      // Handle "data: event: progress" format
      if (trimmedLine.startsWith('data: event: ')) {
        eventType = trimmedLine.slice(13).trim(); // Remove "data: event: "
      }
      // Handle "data: data: {...}" format
      else if (trimmedLine.startsWith('data: data: ')) {
        try {
          const jsonString = trimmedLine.slice(12); // Remove "data: data: "
          eventData = JSON.parse(jsonString);
        } catch (e) {
          console.error('Error parsing SSE data:', e, trimmedLine);
        }
      }
      // Handle standard SSE format (fallback)
      else if (trimmedLine.startsWith('event: ')) {
        eventType = trimmedLine.slice(7).trim();
      } else if (trimmedLine.startsWith('data: ')) {
        try {
          const jsonString = trimmedLine.slice(6);
          eventData = JSON.parse(jsonString);
        } catch {
          // Ignore non-JSON data lines
        }
      }
    });

    if (eventType && eventData) {
      switch (eventType) {
        case 'progress':
          onProgress?.(eventData);
          break;
        case 'complete':
          onComplete?.(eventData);
          break;
        case 'error':
          onError?.(eventData);
          break;
      }
    }
  }

  async getCSVRequirements() {
    return this.request('/api/people/csv-requirements');
  }

  async deleteperson(personId) {
    return this.request(`/api/people/${personId}`, {
      method: 'DELETE',
    });
  }

  async deleteAllPeople() {
    return this.request('/api/people', {
      method: 'DELETE',
    });
  }

  // Face recognition methods
  async detectFaces(imageData) {
    return this.request('/api/recognition/detect', {
      method: 'POST',
      body: JSON.stringify({
        image_data: imageData,
      }),
    });
  }

  async detectFacesFromFile(file) {
    const formData = new FormData();
    formData.append('image', file);

    return this.request('/api/upload/face-image', {
      method: 'POST',
      body: formData,
      headers: {}, // Remove Content-Type to let browser set it with boundary
    });
  }

  // Camera management methods
  async getCameraSettings() {
    return this.request('/api/camera/settings');
  }

  async updateCameraSettings(source = 'default', deviceId = null, rtspUrl = null) {
    return this.request('/api/camera/settings', {
      method: 'POST',
      body: JSON.stringify({
        source: source,
        device_id: deviceId,
        rtsp_url: rtspUrl,
      }),
    });
  }

  async testCamera(source = 'default', deviceId = null, rtspUrl = null) {
    return this.request('/api/camera/test', {
      method: 'POST',
      body: JSON.stringify({
        source: source,
        device_id: deviceId,
        rtsp_url: rtspUrl,
      }),
    });
  }

  async stopRtspStreams() {
    return this.request('/api/rtsp/stop', {
      method: 'POST',
    });
  }

  async stopWebcamStreams() {
    return this.request('/api/webcam/stop', {
      method: 'POST',
    });
  }


  // System methods
  async getSystemStatus() {
    return this.request('/api/system/status');
  }

  async getDetectionStatus() {
    return this.request('/api/system/detection-status');
  }

  async healthCheck() {
    return this.request('/api/system/health');
  }

  // Health check for Express server
  async checkExpressHealth() {
    return this.request('/health');
  }

  // Display settings methods
  async getDisplaySettings() {
    return this.request('/api/display/settings');
  }

  async updateDisplaySettings(timer, backgroundColor, fontColor, cloudColor, useBackgroundImage, backgroundImage, fontFamily, fontSize) {
    return this.request('/api/display/settings', {
      method: 'POST',
      body: JSON.stringify({
        timer: timer,
        background_color: backgroundColor,
        font_color: fontColor,
        cloud_color: cloudColor,
        use_background_image: useBackgroundImage,
        background_image: backgroundImage,
        font_family: fontFamily,
        font_size: fontSize,
      }),
    });
  }

  async uploadBackgroundImage(file) {
    const formData = new FormData();
    formData.append('file', file);

    // Bypass the request method to avoid any header issues
    const url = `${this.baseURL}/api/display/upload-background`;

    // Get auth headers
    const authHeaders = this.getAuthHeader();

    try {
      const response = await fetch(url, {
        method: 'POST',
        body: formData,
        headers: {
          ...authHeaders,
          // Don't set Content-Type - let browser set it with boundary
        },
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error('Upload error response:', errorText);
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error(`Upload Error:`, error);
      throw error;
    }
  }

  async deleteBackgroundImage() {
    return this.request('/api/display/delete-background', {
      method: 'DELETE',
    });
  }

  getBackgroundImage() {
    // Add cache buster to ensure fresh image
    const cacheBuster = Date.now();
    return `/api/display/background-image?t=${cacheBuster}`;
  }

  async fetchImageWithAuth(imageUrl) {
    /**
     * Fetch an image with authentication headers and return as data URL
     * This is needed because <img> tags don't send Authorization headers
     */
    try {
      const url = imageUrl.startsWith('http') ? imageUrl : `${this.baseURL}${imageUrl}`;
      const authHeaders = this.getAuthHeader();

      const response = await fetch(url, {
        method: 'GET',
        headers: {
          ...authHeaders,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch image: ${response.status}`);
      }

      const blob = await response.blob();
      return URL.createObjectURL(blob);
    } catch (error) {
      console.error('Error fetching image with auth:', error);
      return null;
    }
  }

  // MediaPipe/Face Detection settings
  async getMediaPipeSettings() {
    return this.request('/api/mediapipe/settings');
  }

  async getMediaPipePresets() {
    return this.request('/api/mediapipe/presets');
  }

  async updateMediaPipeSettings(settings) {
    return this.request('/api/mediapipe/settings', {
      method: 'POST',
      body: JSON.stringify(settings),
    });
  }

  async applyMediaPipePreset(presetName) {
    return this.request('/api/mediapipe/apply-preset', {
      method: 'POST',
      body: JSON.stringify({ preset: presetName }),
    });
  }

  async optimizeMediaPipeResolution(width, height, targetFps) {
    return this.request('/api/mediapipe/optimize-resolution', {
      method: 'POST',
      body: JSON.stringify({
        width,
        height,
        target_fps: targetFps,
      }),
    });
  }
}

// Helper functions for image processing
export const imageUtils = {
  // Convert file to base64
  fileToBase64: (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => resolve(reader.result);
      reader.onerror = (error) => reject(error);
    });
  },

  // Convert canvas to base64
  canvasToBase64: (canvas) => {
    return canvas.toDataURL('image/jpeg', 0.8);
  },

  // Capture from video element
  captureFromVideo: (videoElement) => {
    const canvas = document.createElement('canvas');
    canvas.width = videoElement.videoWidth;
    canvas.height = videoElement.videoHeight;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoElement, 0, 0);

    return canvas.toDataURL('image/jpeg', 0.8);
  },

  // Validate image file
  validateImageFile: (file) => {
    const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    const maxSize = 10 * 1024 * 1024; // 10MB

    if (!validTypes.includes(file.type)) {
      throw new Error('Invalid file type. Please upload a JPEG, PNG, or WebP image.');
    }

    if (file.size > maxSize) {
      throw new Error('File too large. Please upload an image smaller than 10MB.');
    }

    return true;
  },
};

// WebCamera utilities
export const webcamUtils = {
  // Get user media with video constraints
  async getUserMedia(constraints = {}) {
    const defaultConstraints = {
      video: {
        width: { ideal: 1920, max: 4096 },   // Default to 1080p, allow up to 4K
        height: { ideal: 1080, max: 2304 },  // Default to 1080p, allow up to 4K
        frameRate: { ideal: 30, min: 15 },
        facingMode: 'user',
      },
      audio: false,
    };

    const finalConstraints = {
      ...defaultConstraints,
      ...constraints,
    };

    try {
      return await navigator.mediaDevices.getUserMedia(finalConstraints);
    } catch (error) {
      console.error('Error accessing webcam:', error);
      throw new Error('Unable to access webcam. Please check permissions.');
    }
  },

  // Stop media stream
  stopStream: (stream) => {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
  },

  // Check if webcam is available
  async isWebcamAvailable() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      return devices.some((device) => device.kind === 'videoinput');
    } catch (error) {
      console.error('Error checking webcam availability:', error);
      return false;
    }
  },

  // Get list of video input devices
  async getVideoDevices() {
    try {
      // First check if we have any video devices (this works without permission)
      let devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevices = devices.filter((device) => device.kind === 'videoinput');

      // If devices don't have labels, we need to request permission first
      if (videoDevices.length > 0 && !videoDevices[0].label) {
        console.log('📹 Requesting camera permission to get device labels...');
        try {
          // Request camera permission
          const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          // Stop the stream immediately after getting permission
          stream.getTracks().forEach(track => track.stop());

          // Now enumerate again with permission
          devices = await navigator.mediaDevices.enumerateDevices();
          return devices.filter((device) => device.kind === 'videoinput');
        } catch (permissionError) {
          console.warn('Camera permission denied:', permissionError);
          // Return empty array when permission denied to respect user's choice
          return [];
        }
      }

      return videoDevices;
    } catch (error) {
      console.error('Error getting video devices:', error);
      return [];
    }
  },
};

// Create singleton instance
const apiService = new ApiService();

export default apiService;