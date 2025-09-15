// API service for communicating with Express/FastAPI backend

const BASE_URL = 'http://localhost:8000';

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

    const config = {
      ...defaultOptions,
      ...options,
      headers: {
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

  // Student management methods
  async getStudents() {
    return this.request('/api/students');
  }

  async registerStudent(studentId, studentName, imageData) {
    return this.request('/api/students/register', {
      method: 'POST',
      body: JSON.stringify({
        student_id: studentId,
        student_name: studentName,
        image_data: imageData,
      }),
    });
  }

  async deleteStudent(studentId) {
    return this.request(`/api/students/${studentId}`, {
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

  async updateCameraSettings(rtspUrl = '') {
    return this.request('/api/camera/settings', {
      method: 'POST',
      body: JSON.stringify({
        rtsp_url: rtspUrl,
      }),
    });
  }

  async testCamera(rtspUrl = '') {
    return this.request('/api/camera/test', {
      method: 'POST',
      body: JSON.stringify({
        rtsp_url: rtspUrl,
      }),
    });
  }

  // System methods
  async getSystemStatus() {
    return this.request('/api/system/status');
  }

  async healthCheck() {
    return this.request('/api/system/health');
  }

  // Health check for Express server
  async checkExpressHealth() {
    return this.request('/health');
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
      const devices = await navigator.mediaDevices.enumerateDevices();
      return devices.filter((device) => device.kind === 'videoinput');
    } catch (error) {
      console.error('Error getting video devices:', error);
      return [];
    }
  },
};

// Create singleton instance
const apiService = new ApiService();

export default apiService;