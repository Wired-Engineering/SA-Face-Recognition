// Welcome Canvas Popup Service
// Manages opening and closing of the Welcome Canvas popup window
//
// Features:
// - Dynamic URL detection for deployment flexibility
// - Standard popup mode with window controls
// - Enhanced kiosk mode with fullscreen and cursor hiding
// - Real-time Socket.IO connection using detected endpoints

class WelcomePopupService {
  constructor() {
    this.popupWindow = null;
    this.isOpen = false;
    this.baseUrl = this.detectBaseUrl();
    this.settings = {
      backgroundColor: '#E1EBFF',
      fontColor: '#00243D',
      timer: 5,
      useBackgroundImage: false,
      backgroundImage: null,
      fontFamily: 'Inter',
      fontSize: 'medium'
    };
  }

  // Dynamically detect base URL for deployment flexibility
  detectBaseUrl() {
    // Use current window's origin (works for any FQDN/port/protocol)
    const origin = window.location.origin;
    console.log('🌐 Detected base URL for welcome popup:', origin);
    return origin;
  }

  // Update display settings
  updateSettings(newSettings) {
    this.settings = { ...this.settings, ...newSettings };
  }

  // Open Welcome Canvas popup (only if not already open)
  open(displaySettings = {}, kioskMode = false) {
    // If popup is already open, just update settings and return existing window
    if (this.isPopupOpen()) {
      this.updateSettings(displaySettings);
      this.sendSettingsUpdate();
      console.log('✅ Welcome Canvas popup already open, updated settings');
      return this.popupWindow;
    }

    // Update settings
    this.updateSettings(displaySettings);

    if (kioskMode) {
      return this.openKioskMode(displaySettings);
    }

    return this.openStandardMode(displaySettings);
  }

  // Standard popup window mode
  openStandardMode() {
    // Calculate window position (centered on screen)
    const width = 600;
    const height = 700;
    const left = (window.screen.width - width) / 2;
    const top = (window.screen.height - height) / 2;

    // Enhanced window features for better kiosk-like experience
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
      'directories=no',
      'titlebar=no',
      'chrome=no',
      'copyhistory=no',
      'personalbar=no'
    ].join(',');

    return this.createPopupWindow(features, false);
  }

  // Enhanced kiosk mode with fullscreen attempts
  openKioskMode() {
    console.log('🖥️ Opening in enhanced kiosk mode');

    // Try to use fullscreen API on current window first
    this.attemptFullscreen();

    // Kiosk-optimized window features
    const features = [
      'fullscreen=yes',
      'width=' + window.screen.width,
      'height=' + window.screen.height,
      'left=0',
      'top=0',
      'resizable=no',
      'scrollbars=no',
      'status=no',
      'menubar=no',
      'toolbar=no',
      'location=no',
      'directories=no',
      'titlebar=no',
      'chrome=no',
      'modal=yes'
    ].join(',');

    return this.createPopupWindow(features, true);
  }

  // Attempt to enable fullscreen on current window
  attemptFullscreen() {
    try {
      if (document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen();
      } else if (document.documentElement.webkitRequestFullscreen) {
        document.documentElement.webkitRequestFullscreen();
      } else if (document.documentElement.msRequestFullscreen) {
        document.documentElement.msRequestFullscreen();
      }
    } catch (error) {
      console.log('ℹ️ Fullscreen API not available or blocked:', error.message);
    }
  }

  // Create popup window with dynamic URL construction
  createPopupWindow(features, isKioskMode) {
    // Build URL with settings as query parameters (exclude large backgroundImage)
    const popupUrl = this.buildPopupUrl(isKioskMode);

    try {
      // Open popup window
      this.popupWindow = window.open(popupUrl, 'WelcomeScreen', features);

      if (this.popupWindow) {
        this.isOpen = true;

        // For kiosk mode, try to maximize the popup window
        if (isKioskMode && this.popupWindow.moveTo && this.popupWindow.resizeTo) {
          try {
            this.popupWindow.moveTo(0, 0);
            this.popupWindow.resizeTo(window.screen.width, window.screen.height);
          } catch (error) {
            console.log('ℹ️ Cannot programmatically resize popup window:', error.message);
          }
        }

        // Monitor popup window
        this.monitorPopup();

        console.log(`✅ Welcome Canvas popup opened in ${isKioskMode ? 'kiosk' : 'standard'} mode`);
        console.log(`🔗 Popup URL: ${popupUrl}`);

        if (isKioskMode) {
          console.log(`💡 For true kiosk mode without URL bar, launch browser with:`);
          console.log(`   Chrome: google-chrome --kiosk --app="${popupUrl}"`);
          console.log(`   Firefox: firefox --kiosk "${popupUrl}"`);
        }

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

  // Build dynamic popup URL
  buildPopupUrl(isKioskMode = false) {
    const params = new URLSearchParams({
      backgroundColor: this.settings.backgroundColor,
      fontColor: this.settings.fontColor,
      timer: this.settings.timer.toString(),
      persistent: 'true',  // Flag for persistent mode
      useBackgroundImage: this.settings.useBackgroundImage ? 'true' : 'false',
      fontFamily: this.settings.fontFamily || 'Inter',
      fontSize: this.settings.fontSize || 'medium',
      kiosk: isKioskMode ? 'true' : 'false',
      // Pass the base URL so popup knows where to connect
      apiBase: this.baseUrl
    });

    const popupUrl = `${this.baseUrl}/welcome-popup.html?${params.toString()}`;
    return popupUrl;
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

  // Enable kiosk mode on existing popup
  enableKioskMode() {
    if (this.isPopupOpen()) {
      try {
        this.popupWindow.postMessage({
          type: 'enable_kiosk_mode'
        }, window.location.origin);
        console.log('🖥️ Sent kiosk mode enable command to popup');
      } catch (error) {
        console.error('Failed to send kiosk mode command to popup:', error);
      }
    } else {
      console.warn('Cannot enable kiosk mode: no popup window open');
    }
  }

  // Close popup window
  close() {
    if (this.popupWindow && !this.popupWindow.closed) {
      this.popupWindow.close();
      console.log('🔴 Welcome Canvas popup closed');
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
        console.log('🔴 Welcome Canvas popup was closed');
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
      person_id: 'STU001',
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
export const openWelcomePopup = (displaySettings, kioskMode = false) => {
  return welcomePopupService.open(displaySettings, kioskMode);
};

export const openWelcomePopupKiosk = (displaySettings) => {
  return welcomePopupService.open(displaySettings, true);
};

export const enableWelcomePopupKiosk = () => {
  welcomePopupService.enableKioskMode();
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