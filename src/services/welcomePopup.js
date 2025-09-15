// Welcome Screen Popup Service
// Manages opening and closing of the welcome screen popup window

class WelcomePopupService {
  constructor() {
    this.popupWindow = null;
    this.isOpen = false;
    this.settings = {
      backgroundColor: '#E1EBFF',
      fontColor: '#00243D',
      timer: 5
    };
  }

  // Update display settings
  updateSettings(newSettings) {
    this.settings = { ...this.settings, ...newSettings };
  }

  // Open welcome screen popup (only if not already open)
  open(displaySettings = {}) {
    // If popup is already open, just update settings and return existing window
    if (this.isPopupOpen()) {
      this.updateSettings(displaySettings);
      this.sendSettingsUpdate();
      console.log('✅ Welcome screen popup already open, updated settings');
      return this.popupWindow;
    }

    // Update settings
    this.updateSettings(displaySettings);

    // Calculate window position (centered on screen)
    const width = 600;
    const height = 700;
    const left = (window.screen.width - width) / 2;
    const top = (window.screen.height - height) / 2;

    // Window features
    const features = [
      `width=${width}`,
      `height=${height}`,
      `left=${left}`,
      `top=${top}`,
      'resizable=no',
      'scrollbars=no',
      'status=no',
      'menubar=no',
      'toolbar=no',
      'location=no',
      'directories=no'
    ].join(',');

    // Build URL with settings as query parameters
    const baseUrl = window.location.origin + '/welcome-popup.html';
    const params = new URLSearchParams({
      backgroundColor: this.settings.backgroundColor,
      fontColor: this.settings.fontColor,
      timer: this.settings.timer.toString(),
      persistent: 'true'  // Flag for persistent mode
    });
    const popupUrl = `${baseUrl}?${params.toString()}`;

    try {
      // Open popup window
      this.popupWindow = window.open(popupUrl, 'WelcomeScreen', features);

      if (this.popupWindow) {
        this.isOpen = true;

        // Monitor popup window
        this.monitorPopup();

        console.log('✅ Welcome screen popup opened in persistent mode');
        return this.popupWindow;
      } else {
        console.error('❌ Failed to open popup window (popup blocked?)');
        return null;
      }
    } catch (error) {
      console.error('❌ Error opening popup window:', error);
      return null;
    }
  }

  // Send settings update to existing popup
  sendSettingsUpdate() {
    if (this.isPopupOpen()) {
      try {
        this.popupWindow.postMessage({
          type: 'settings_update',
          settings: this.settings
        }, window.location.origin);
      } catch (error) {
        console.error('Failed to send settings update to popup:', error);
      }
    }
  }

  // Close popup window
  close() {
    if (this.popupWindow && !this.popupWindow.closed) {
      this.popupWindow.close();
      console.log('🔴 Welcome screen popup closed');
    }
    this.popupWindow = null;
    this.isOpen = false;
  }

  // Check if popup is open
  isPopupOpen() {
    return this.isOpen && this.popupWindow && !this.popupWindow.closed;
  }

  // Monitor popup window state
  monitorPopup() {
    const checkInterval = setInterval(() => {
      if (!this.popupWindow || this.popupWindow.closed) {
        this.isOpen = false;
        this.popupWindow = null;
        clearInterval(checkInterval);
        console.log('🔴 Welcome screen popup was closed');
      }
    }, 1000);
  }

  // Auto-open popup when face is recognized (call this from detection)
  showRecognition(userData, displaySettings = {}) {
    if (!this.isPopupOpen()) {
      this.open(displaySettings);
    }

    // Send user data to popup if it's open
    if (this.isPopupOpen()) {
      try {
        this.popupWindow.postMessage({
          type: 'recognition',
          user: userData,
          timestamp: Date.now()
        }, window.location.origin);
      } catch (error) {
        console.error('Failed to send recognition data to popup:', error);
      }
    }
  }

  // Test popup functionality
  testPopup(displaySettings = {}) {
    const testUser = {
      name: 'John Doe',
      student_id: 'STU001',
      department: 'Computer Science',
      confidence: 0.95,
      photo: null
    };

    this.showRecognition(testUser, displaySettings);
  }
}

// Create singleton instance
const welcomePopupService = new WelcomePopupService();

// Helper functions for easy access
export const openWelcomePopup = (displaySettings) => {
  return welcomePopupService.open(displaySettings);
};

export const closeWelcomePopup = () => {
  welcomePopupService.close();
};

export const showRecognition = (userData, displaySettings) => {
  welcomePopupService.showRecognition(userData, displaySettings);
};

export const testWelcomePopup = (displaySettings) => {
  welcomePopupService.testPopup(displaySettings);
};

export const isWelcomePopupOpen = () => {
  return welcomePopupService.isPopupOpen();
};

export default welcomePopupService;