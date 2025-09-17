// API service for communicating with Express/FastAPI backend

const BASE_URL = window.location.origin;

class ApiService {
  constructor() {
    this.baseURL = BASE_URL;
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const defaultOptions = {
      headers: {
        'Content-Type': 'application/json',
      },
    };

    // Don't merge headers if options.headers is explicitly empty (for file uploads)
    const config = {
      ...defaultOptions,
      ...options,
      headers: Object.keys(options.headers || {}).length === 0 && options.body instanceof FormData
        ? {} // Empty headers for FormData uploads
        : {
            ...defaultOptions.headers,
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
    return this.request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        admin_id: adminId,
        password: password,
      }),
    });
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

  async registerperson(personName, personTitle, imageData) {
    return this.request('/api/people/register', {
      method: 'POST',
      body: JSON.stringify({
        person_name: personName,
        person_title: personTitle,
        image_data: imageData,
      }),
    });
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

  async updateDisplaySettings(timer, backgroundColor, fontColor, useBackgroundImage, backgroundImage, fontFamily, fontSize) {
    return this.request('/api/display/settings', {
      method: 'POST',
      body: JSON.stringify({
        timer: timer,
        background_color: backgroundColor,
        font_color: fontColor,
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
    try {
      const response = await fetch(url, {
        method: 'POST',
        body: formData,
        // No headers - let browser set Content-Type with boundary
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
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 },
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