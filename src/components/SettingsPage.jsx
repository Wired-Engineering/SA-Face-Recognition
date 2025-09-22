import { useState, useEffect } from 'react';
import {
  Stack,
  Title,
  TextInput,
  PasswordInput,
  Button,
  Group,
  Tabs,
  NumberInput,
  Alert,
  ColorPicker,
  Text,
  Select,
  Switch,
  Divider,
  Box,
  Card,
  useMantineTheme,
  Image,
  ScrollArea,
  LoadingOverlay,
  Flex,
  Badge,
  FileInput,
} from '@mantine/core';
import {
  IconUser,
  IconLock,
  IconClock,
  IconCamera,
  IconDeviceFloppy,
  IconColorPicker,
  IconPalette,
  IconEye,
  IconTrash,
  IconUpload,
  IconPhoto,
  IconRefresh,
  IconUsersGroup,
  IconSettings,
  IconMoodSmile,
  IconInfoCircle,
  IconRocket,
  IconBadge,
} from '@tabler/icons-react';
import apiService, { webcamUtils } from '../services/api';
import welcomePopupService, { testWelcomePopup, closeWelcomePopup, isWelcomePopupOpen } from '../services/welcomePopup';

export function SettingsPage({ onSaveSettings }) {
  const theme = useMantineTheme();
  // Admin settings state
  const [oldAdminId, setOldAdminId] = useState('');
  const [oldAdminPass, setOldAdminPass] = useState('');
  const [newAdminId, setNewAdminId] = useState('');
  const [newAdminPass, setNewAdminPass] = useState('');
  const [newAdminPassConf, setNewAdminPassConf] = useState('');

  // Welcome Canvas state
  const [displayTimer, setDisplayTimer] = useState(5);
  const [backgroundColor, setBackgroundColor] = useState(theme.colors.accent[1]);
  const [fontColor, setFontColor] = useState(theme.other.signatureNavy);
  const [cloudColor, setCloudColor] = useState('#4ECDC4');
  const [useBackgroundImage, setUseBackgroundImage] = useState(false);
  const [backgroundImagePreview, setBackgroundImagePreview] = useState(null);
  const [fontFamily, setFontFamily] = useState('Inter');
  const [fontSize, setFontSize] = useState('medium');

  // Camera settings state
  const [cameraDevices, setCameraDevices] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('default');
  const [rtspUrl, setRtspUrl] = useState('');

  // Data management state
  const [people, setPeople] = useState([]);
  const [peopleLoading, setPeopleLoading] = useState(false);
  const [uploadingPhotos, setUploadingPhotos] = useState({});

  // MediaPipe settings state
  const [mediapipeSettings, setMediapipeSettings] = useState({
    detection_confidence: 0.6,  // Good default for video
    tracking_confidence: 0.7,   // Optimized for video tracking
    max_faces: 20,
    refine_landmarks: true,     // Always use high quality
    unlimited_faces: false,
    include_landmarks: false    // Debug only
  });
  const [mediapipePresets, setMediapipePresets] = useState({});
  const [mediapipePerformance, setMediapipePerformance] = useState({});
  const [mediapipeLoading, setMediapipeLoading] = useState(false);

  // Loading and error states
  const [adminLoading, setAdminLoading] = useState(false);
  const [displayLoading] = useState(false);
  const [cameraLoading, setCameraLoading] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Test popup state
  const [testPopupOpen, setTestPopupOpen] = useState(false);

  // Load available cameras and saved settings on component mount
  useEffect(() => {
    const loadCamerasAndSettings = async () => {
      try {
        // Load available camera devices
        const devices = await webcamUtils.getVideoDevices();
        console.log('Available cameras:', devices);
        setCameraDevices(devices);

        // Load saved camera settings first to check current configuration
        const cameraSettings = await apiService.getCameraSettings();

        // If no cameras are available, only auto-set RTSP if there's no valid existing config
        if (devices.length === 0) {
          console.log('No cameras available');

          // Check if we already have a valid RTSP configuration
          if (cameraSettings.success && cameraSettings.source === 'rtsp') {
            console.log('Using existing RTSP configuration');
            setSelectedCamera('rtsp');
            setRtspUrl(cameraSettings.rtsp_url || '');
          } else {
            // Only set default RTSP if no valid config exists or config uses invalid camera
            console.log('No valid camera config found, defaulting to RTSP');
            setSelectedCamera('rtsp');

            try {
              await apiService.updateCameraSettings('rtsp', null, '');
              console.log('✅ Automatically updated config to use RTSP (no cameras detected)');
            } catch (error) {
              console.warn('Failed to auto-save RTSP config:', error);
            }
          }
        }

        // Load saved camera settings from backend (only if cameras are available)
        if (devices.length > 0) {
          if (cameraSettings.success || cameraSettings.source) {
            if (cameraSettings.source === 'rtsp') {
              setSelectedCamera('rtsp');
              setRtspUrl(cameraSettings.rtsp_url || '');
            } else if (cameraSettings.source === 'device' && cameraSettings.device_id) {
              // Find which camera index this device ID corresponds to
              const deviceIndex = devices.findIndex(device => device.deviceId === cameraSettings.device_id);
              if (deviceIndex >= 0) {
                setSelectedCamera(`camera_${deviceIndex}`);
                console.log(`Loaded camera setting: device_id ${cameraSettings.device_id} → camera_${deviceIndex}`);
              } else {
                console.warn(`Saved device ID ${cameraSettings.device_id} not found in available devices`);
                setSelectedCamera('default');
              }
            } else {
              setSelectedCamera(cameraSettings.source || 'default');
            }
          }
        }

        // Load Canvas Settings from backend
        const displaySettings = await apiService.getDisplaySettings();
        if (displaySettings.success) {
          setDisplayTimer(displaySettings.timer || 5);
          setBackgroundColor(displaySettings.background_color || theme.colors.accent[1]);
          setFontColor(displaySettings.font_color || theme.other.signatureNavy);
          setCloudColor(displaySettings.cloud_color || '#4ECDC4');
          setUseBackgroundImage(displaySettings.use_background_image || false);
          setFontFamily(displaySettings.font_family || 'Inter');
          setFontSize(displaySettings.font_size || 'medium');

          // If there's a background image on the server, show the actual image URL
          if (displaySettings.has_background_image) {
            // Get the actual image URL from the API
            const imageUrl = apiService.getBackgroundImage();
            setBackgroundImagePreview(imageUrl);
          }
        }

        // Load people data for data management tab
        await loadPeopleData();

        // Load MediaPipe settings
        await loadMediaPipeSettings();
      } catch (error) {
        console.error('Error loading settings:', error);
      }
    };
    loadCamerasAndSettings();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadPeopleData = async () => {
    try {
      setPeopleLoading(true);
      const response = await apiService.getpeople();
      if (response.success) {
        setPeople(response.people || []);
      } else {
        setError('Failed to load people data');
      }
    } catch (error) {
      setError('Error loading people: ' + error.message);
      console.error('People loading error:', error);
    } finally {
      setPeopleLoading(false);
    }
  };

  const loadMediaPipeSettings = async () => {
    try {
      setMediapipeLoading(true);

      // Load current settings
      const response = await fetch('/api/mediapipe/settings');
      const data = await response.json();

      if (data.success) {
        setMediapipeSettings(data.settings);
        setMediapipePerformance(data.performance || {});
      }

      // Load presets
      const presetsResponse = await fetch('/api/mediapipe/presets');
      const presetsData = await presetsResponse.json();

      if (presetsData.success) {
        setMediapipePresets(presetsData.presets);
      }
    } catch (error) {
      console.error('Error loading MediaPipe settings:', error);
      setError('Failed to load MediaPipe settings: ' + error.message);
    } finally {
      setMediapipeLoading(false);
    }
  };

  const handleUpdateMediaPipeSettings = async (newSettings) => {
    try {
      setMediapipeLoading(true);
      setError('');
      setSuccess('');

      const response = await fetch('/api/mediapipe/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings)
      });

      const data = await response.json();

      if (data.success) {
        setMediapipeSettings(prev => ({ ...prev, ...newSettings }));
        setSuccess('MediaPipe settings updated successfully!');

        // Reload to get updated performance stats
        await loadMediaPipeSettings();

        onSaveSettings?.({
          type: 'mediapipe',
          ...newSettings
        });
      } else {
        setError(data.message || 'Failed to update MediaPipe settings');
      }
    } catch (error) {
      setError('Failed to update MediaPipe settings: ' + error.message);
      console.error('MediaPipe update error:', error);
    } finally {
      setMediapipeLoading(false);
    }
  };

  const handleApplyPreset = async (presetName) => {
    try {
      setMediapipeLoading(true);
      setError('');
      setSuccess('');

      const response = await fetch('/api/mediapipe/apply-preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset: presetName })
      });

      const data = await response.json();

      if (data.success) {
        setSuccess(`Applied preset: ${mediapipePresets[presetName]?.name || presetName}`);

        // Reload settings to reflect the preset
        await loadMediaPipeSettings();

        onSaveSettings?.({
          type: 'mediapipe_preset',
          preset: presetName
        });
      } else {
        setError(data.message || 'Failed to apply preset');
      }
    } catch (error) {
      setError('Failed to apply preset: ' + error.message);
      console.error('Preset apply error:', error);
    } finally {
      setMediapipeLoading(false);
    }
  };

  const handleOptimizeResolution = async () => {
    try {
      setMediapipeLoading(true);
      setError('');
      setSuccess('');

      // Use common camera resolutions for optimization
      const response = await fetch('/api/mediapipe/optimize-resolution', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          width: 1280,
          height: 720,
          target_fps: 30
        })
      });

      const data = await response.json();

      if (data.success) {
        setSuccess('Resolution optimization applied!');

        // Reload settings to reflect the optimization
        await loadMediaPipeSettings();

        onSaveSettings?.({
          type: 'mediapipe_optimization',
          resolution: '1280x720'
        });
      } else {
        setError(data.message || 'Failed to optimize resolution');
      }
    } catch (error) {
      setError('Failed to optimize resolution: ' + error.message);
      console.error('Resolution optimization error:', error);
    } finally {
      setMediapipeLoading(false);
    }
  };

  const handleAdminChange = async () => {
    if (newAdminPass !== newAdminPassConf) {
      setError('New passwords do not match!');
      return;
    }
    if (!oldAdminId || !oldAdminPass || !newAdminId || !newAdminPass) {
      setError('Please fill in all fields');
      return;
    }

    setAdminLoading(true);
    setError('');
    setSuccess('');

    try {
      const result = await apiService.changeAdminPassword(
        oldAdminId,
        oldAdminPass,
        newAdminId,
        newAdminPass,
        newAdminPassConf
      );

      if (result.success) {
        setSuccess('Admin credentials updated successfully!');
        // Reset form
        setOldAdminId('');
        setOldAdminPass('');
        setNewAdminId('');
        setNewAdminPass('');
        setNewAdminPassConf('');

        // Call parent callback if provided
        onSaveSettings?.({
          type: 'admin',
          oldId: oldAdminId,
          oldPassword: oldAdminPass,
          newId: newAdminId,
          newPassword: newAdminPass,
        });
      } else {
        setError(result.message || 'Failed to update admin credentials');
      }
    } catch (error) {
      setError('Failed to update admin credentials: ' + error.message);
      console.error('Admin change error:', error);
    } finally {
      setAdminLoading(false);
    }
  };

  const handleSaveDisplay = async () => {
    const settings = {
      timer: displayTimer,
      backgroundColor,
      fontColor,
      cloudColor,
      useBackgroundImage,
      backgroundImage: backgroundImagePreview,
      fontFamily,
      fontSize,
    };

    try {
      // Save to backend (don't send background image data, just the flag)
      const result = await apiService.updateDisplaySettings(
        displayTimer,
        backgroundColor,
        fontColor,
        cloudColor,
        useBackgroundImage,
        null, // Don't send image data
        fontFamily,
        fontSize
      );

      if (result.success) {
        // Also save to localStorage for welcome popup access
        localStorage.setItem('faceRecognitionDisplaySettings', JSON.stringify(settings));

        setSuccess('Canvas Settings saved successfully!');

        // If popup is open, send updated settings to it
        if (isWelcomePopupOpen()) {
          console.log('💾 Settings saved, updating welcome popup');
          // Send settings update to existing popup window
          welcomePopupService.updateSettings(settings);
          welcomePopupService.sendSettingsUpdate();
        }

        onSaveSettings?.({
          type: 'display',
          ...settings,
        });
      } else {
        setError('Failed to save Canvas Settings');
      }
    } catch (error) {
      setError('Failed to save Canvas Settings: ' + error.message);
      console.error('Display save error:', error);
    }
  };

  const handleTestWelcomePopup = () => {
    const currentSettings = {
      backgroundColor,
      fontColor,
      cloudColor,
      timer: displayTimer,
      useBackgroundImage,
      backgroundImage: backgroundImagePreview,
      fontFamily,
      fontSize
    };
    testWelcomePopup(currentSettings);
    setTestPopupOpen(true);
  };

  const handleBackgroundImageUpload = async (file) => {
    if (!file) {
      setError('No file selected');
      return;
    }

    try {
      setError('');
      const result = await apiService.uploadBackgroundImage(file);
      if (result.success) {
        setBackgroundImagePreview(result.image_url);
        setUseBackgroundImage(true);
        setSuccess(result.message || 'Background image uploaded successfully!');

        // If popup is open, send updated settings to it
        if (isWelcomePopupOpen()) {
          const settings = {
            backgroundColor,
            fontColor,
            cloudColor,
            timer: displayTimer,
            useBackgroundImage: true,
            backgroundImage: result.image_url,
            fontFamily,
            fontSize
          };
          welcomePopupService.updateSettings(settings);
          welcomePopupService.sendSettingsUpdate();
        }
      } else {
        setError(result.message || 'Failed to upload background image');
      }
    } catch (error) {
      setError('Failed to upload background image: ' + error.message);
      console.error('Background upload error:', error);
    }
  };

  const handleDeleteBackgroundImage = async () => {
    try {
      setError('');
      const result = await apiService.deleteBackgroundImage();
      if (result.success) {
        setBackgroundImagePreview(null);
        setUseBackgroundImage(false);
        setSuccess('Background image deleted successfully!');

        // If popup is open, update it to remove the background image
        if (isWelcomePopupOpen()) {
          const settings = {
            backgroundColor,
            fontColor,
            cloudColor,
            timer: displayTimer,
            useBackgroundImage: false,
            backgroundImage: null,
            fontFamily,
            fontSize
          };
          welcomePopupService.updateSettings(settings);
          welcomePopupService.sendSettingsUpdate();
        }
      } else {
        setError(result.message || 'Failed to delete background image');
      }
    } catch (error) {
      setError('Failed to delete background image: ' + error.message);
      console.error('Background delete error:', error);
    }
  };

  // Note: Auto-update only happens when Save button is pressed, not on parameter changes

  // Monitor popup state (check if it was closed manually)
  useEffect(() => {
    if (testPopupOpen) {
      const checkInterval = setInterval(() => {
        if (!isWelcomePopupOpen()) {
          setTestPopupOpen(false);
          clearInterval(checkInterval);
        }
      }, 1000);

      return () => clearInterval(checkInterval);
    }
  }, [testPopupOpen]);

  const handleTestCamera = async () => {
    setCameraLoading(true);
    setError('');

    try {
      if (selectedCamera === 'rtsp') {
        // For RTSP, use backend testing since browser can't access RTSP
        if (!rtspUrl || rtspUrl.trim() === '') {
          setError('Please enter an RTSP URL before testing');
          return;
        }

        const result = await apiService.testCamera('rtsp', null, rtspUrl);
        if (result.success) {
          setSuccess('RTSP camera test successful!');
        } else {
          setError(result.message || 'RTSP camera test failed');
        }
      } else {
        // For browser cameras (webcam, device, default), use browser-based testing
        await testBrowserCamera();
      }
    } catch (error) {
      setError('Camera test failed: ' + error.message);
      console.error('Camera test error:', error);
    } finally {
      setCameraLoading(false);
    }
  };

  const testBrowserCamera = async () => {
    let stream = null;
    try {
      // Determine which camera to test - request highest available resolution
      let constraints = {
        video: {
          width: { ideal: 3840, max: 4096 },   // Request up to 4K
          height: { ideal: 2160, max: 2304 },  // Request up to 4K
          frameRate: { ideal: 30, min: 15 }
        },
        audio: false
      };

      if (selectedCamera === 'default') {
        // Use default camera
        constraints.video.facingMode = 'user';
        console.log('🎥 Testing default camera');
      } else if (selectedCamera.startsWith('camera_')) {
        // Use specific camera by deviceId
        const cameraIndex = parseInt(selectedCamera.replace('camera_', ''));
        if (cameraIndex < cameraDevices.length) {
          const device = cameraDevices[cameraIndex];
          constraints.video.deviceId = { exact: device.deviceId };
          console.log(`🎥 Testing camera: ${device.label} (${device.deviceId.slice(0, 12)}...)`);
        } else {
          throw new Error('Selected camera not found in available devices');
        }
      }

      // Test camera access
      stream = await navigator.mediaDevices.getUserMedia(constraints);

      // Verify we can get video track
      const videoTracks = stream.getVideoTracks();
      if (videoTracks.length === 0) {
        throw new Error('No video track found in camera stream');
      }

      const videoTrack = videoTracks[0];
      const settings = videoTrack.getSettings();

      setSuccess(`Camera test successful! Resolution: ${settings.width}x${settings.height}, Device: ${videoTrack.label}`);

      // Stop the test stream
      stream.getTracks().forEach(track => track.stop());

    } catch (error) {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }

      if (error.name === 'NotFoundError') {
        throw new Error('Camera not found. Please check if the camera is connected and not in use by another application.');
      } else if (error.name === 'NotAllowedError') {
        throw new Error('Camera access denied. Please allow camera permissions in your browser.');
      } else if (error.name === 'NotReadableError') {
        throw new Error('Camera is already in use by another application.');
      } else {
        throw error;
      }
    }
  };

  const handleSaveCamera = async () => {
    setCameraLoading(true);
    setError('');
    setSuccess('');

    try {
      // Determine the source and parameters for saving
      let source = selectedCamera;
      let deviceId = null;
      let rtspUrlToSave = null;

      if (selectedCamera === 'rtsp') {
        source = 'rtsp';
        rtspUrlToSave = rtspUrl;
        // Validate RTSP URL before saving
        if (!rtspUrl || rtspUrl.trim() === '') {
          setError('Please enter an RTSP URL before saving');
          return;
        }
      } else if (selectedCamera === 'default') {
        source = 'default';
      } else if (selectedCamera.startsWith('camera_')) {
        // It's a camera index - get the actual device ID from our stored devices
        source = 'device';
        const cameraIndex = parseInt(selectedCamera.replace('camera_', ''));
        if (cameraIndex < cameraDevices.length) {
          deviceId = cameraDevices[cameraIndex].deviceId; // Use actual browser device ID
          console.log(`Saving camera ${cameraIndex}: device ID = ${deviceId}`);
        } else {
          setError('Selected camera not found in available devices');
          return;
        }
      } else {
        // Fallback to default
        source = 'default';
      }

      const result = await apiService.updateCameraSettings(source, deviceId, rtspUrlToSave);

      if (result.success) {
        setSuccess('Camera settings saved successfully!');
        onSaveSettings?.({
          type: 'camera',
          source: source,
          device_id: deviceId,
          rtsp_url: rtspUrlToSave,
        });
      } else {
        setError(result.message || 'Failed to save camera settings');
      }
    } catch (error) {
      setError('Failed to save camera settings: ' + error.message);
      console.error('Camera save error:', error);
    } finally {
      setCameraLoading(false);
    }
  };

  const handleDeleteAllPeople = async () => {
    if (!window.confirm('Are you sure you want to delete all people records? This action cannot be undone.')) {
      return;
    }

    setDeleteLoading(true);
    setError('');
    setSuccess('');

    try {
      const result = await apiService.deleteAllPeople();

      if (result.success) {
        setSuccess(`All ${result.deleted_count} people deleted successfully!`);
        // Refresh the people list
        await loadPeopleData();

        onSaveSettings?.({
          type: 'deleteAllPeople',
          deletedCount: result.deleted_count
        });
      } else {
        setError(result.message || 'Failed to delete all people');
      }
    } catch (error) {
      setError('Failed to delete all people: ' + error.message);
      console.error('Delete all people error:', error);
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleDeletePerson = async (personId, personName) => {
    if (!window.confirm(`Are you sure you want to delete ${personName}? This action cannot be undone.`)) {
      return;
    }

    try {
      setError('');
      const result = await apiService.deleteperson(personId);

      if (result.success) {
        setSuccess(`${personName} deleted successfully!`);
        // Refresh the people list
        await loadPeopleData();

        onSaveSettings?.({
          type: 'deletePerson',
          personId,
          personName
        });
      } else {
        setError(result.message || `Failed to delete ${personName}`);
      }
    } catch (error) {
      setError(`Failed to delete ${personName}: ` + error.message);
      console.error('Delete person error:', error);
    }
  };

  const handleUploadAdditionalPhoto = async (personId, personName, file) => {
    if (!file) return;

    setUploadingPhotos(prev => ({ ...prev, [personId]: true }));

    try {
      // Validate and convert file
      const imageData = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });

      const result = await apiService.addAdditionalPhoto(personId, imageData);

      if (result.success) {
        setSuccess(`Additional photo added for ${personName}!`);
        // Refresh the people list to show updated photo count
        await loadPeopleData();
        setTimeout(() => setSuccess(''), 3000);
      } else {
        setError(result.message || `Failed to add photo for ${personName}`);
      }
    } catch (error) {
      setError(`Failed to add photo for ${personName}: ` + error.message);
      console.error('Upload photo error:', error);
    } finally {
      setUploadingPhotos(prev => ({ ...prev, [personId]: false }));
    }
  };

  return (
    <Box style={{ width: '100%', minHeight: '100%' }}>
      <Box style={{ padding: '24px' }}>
        <Title order={2} ta="center" mb="xl">
          System Settings
        </Title>

        {/* Global Error Alert */}
        {error && (
          <Alert
            color="red"
            title="Error"
            mb="md"
            onClose={() => setError('')}
            withCloseButton
          >
            {error}
          </Alert>
        )}

        {/* Global Success Alert */}
        {success && (
          <Alert
            color="green"
            title="Success"
            mb="md"
            onClose={() => setSuccess('')}
            withCloseButton
          >
            {success}
          </Alert>
        )}

      <Tabs defaultValue="admin" color="blue">
        <Tabs.List grow mb="md">
          <Tabs.Tab value="admin" leftSection={<IconUser size={16} />}>
            Admin Settings
          </Tabs.Tab>
          <Tabs.Tab value="display" leftSection={<IconPalette size={16} />}>
            Canvas Settings
          </Tabs.Tab>
          <Tabs.Tab value="camera" leftSection={<IconCamera size={16} />}>
            Camera Settings
          </Tabs.Tab>
          <Tabs.Tab value="mediapipe" leftSection={<IconMoodSmile size={16} />}>
            Face Detection
          </Tabs.Tab>
          <Tabs.Tab value="data" leftSection={<IconTrash size={16} />}>
            Data Management
          </Tabs.Tab>
        </Tabs.List>

        {/* Admin Settings Tab */}
        <Tabs.Panel value="admin">
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="md">
              <Title order={4}>
                Change Admin Credentials
              </Title>

              <Group grow>
                <TextInput
                  label="Old Admin ID"
                  placeholder="Enter current admin ID"
                  value={oldAdminId}
                  onChange={(event) => setOldAdminId(event.currentTarget.value)}
                  leftSection={<IconUser size={16} />}
                />
                <PasswordInput
                  label="Old Password"
                  placeholder="Enter current password"
                  value={oldAdminPass}
                  onChange={(event) => setOldAdminPass(event.currentTarget.value)}
                  leftSection={<IconLock size={16} />}
                />
              </Group>

              <Divider my="sm" />

              <Group grow>
                <TextInput
                  label="New Admin ID"
                  placeholder="Enter new admin ID"
                  value={newAdminId}
                  onChange={(event) => setNewAdminId(event.currentTarget.value)}
                  leftSection={<IconUser size={16} />}
                />
                <PasswordInput
                  label="New Password"
                  placeholder="Enter new password"
                  value={newAdminPass}
                  onChange={(event) => setNewAdminPass(event.currentTarget.value)}
                  leftSection={<IconLock size={16} />}
                />
              </Group>

              <PasswordInput
                label="Confirm New Password"
                placeholder="Confirm new password"
                value={newAdminPassConf}
                onChange={(event) => setNewAdminPassConf(event.currentTarget.value)}
                leftSection={<IconLock size={16} />}
                error={
                  newAdminPassConf &&
                  newAdminPass !== newAdminPassConf
                    ? 'Passwords do not match'
                    : null
                }
              />

              <Button
                leftSection={<IconDeviceFloppy size={16} />}
                onClick={handleAdminChange}
                loading={adminLoading}
                disabled={
                  !oldAdminId ||
                  !oldAdminPass ||
                  !newAdminId ||
                  !newAdminPass ||
                  newAdminPass !== newAdminPassConf ||
                  adminLoading
                }
                color="signature"
              >
                {adminLoading ? 'Changing...' : 'Change Admin'}
              </Button>
            </Stack>
          </Card>
        </Tabs.Panel>

        {/* Canvas Settings Tab */}
        <Tabs.Panel value="display">
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="md">
              <Title order={4}>
                Canvas Preferences
              </Title>

              <NumberInput
                label="Cloud Persistence Timer (seconds)"
                description="How long name clouds remain visible after person leaves detection frame"
                placeholder="Enter timer value"
                value={displayTimer}
                onChange={setDisplayTimer}
                min={1}
                max={60}
                leftSection={<IconClock size={16} />}
              />

              <Divider my="sm" label="Background Settings" labelPosition="left" />

              <Switch
                label="Use Background Image"
                checked={useBackgroundImage}
                onChange={(event) => setUseBackgroundImage(event.currentTarget.checked)}
                description="Toggle between solid color and custom image background"
                styles={{
                  label: { color: 'black' }
                }}
              />

              {useBackgroundImage ? (
                <Stack gap="md">
                  <Group>
                    <Button
                      leftSection={<IconUpload size={16} />}
                      variant="outline"
                      component="label"
                      color="signature"
                    >
                      Upload Background Image
                      <input
                        type="file"
                        hidden
                        accept="image/jpeg,image/jpg,image/png,image/webp"
                        onChange={(e) => handleBackgroundImageUpload(e.target.files[0])}
                      />
                    </Button>
                    {backgroundImagePreview && (
                      <Button
                        leftSection={<IconTrash size={16} />}
                        variant="filled"
                        color="red"
                        onClick={handleDeleteBackgroundImage}
                        styles={{
                          root: {
                            backgroundColor: '#fa5252',
                            color: 'white',
                            '&:hover': {
                              backgroundColor: '#e03131'
                            }
                          }
                        }}
                      >
                        Delete Background
                      </Button>
                    )}
                  </Group>

                  {backgroundImagePreview && (
                    <Box>
                      <Text size="sm" fw={500} mb="xs">
                        Current Background:
                      </Text>
                      <Box
                        style={{
                          width: '100%',
                          maxWidth: '400px',
                          height: '225px',
                          border: '2px solid #dee2e6',
                          borderRadius: '8px',
                          overflow: 'hidden',
                          backgroundImage: `url(${backgroundImagePreview})`,
                          backgroundSize: 'cover',
                          backgroundPosition: 'center',
                          backgroundColor: 'transparent',
                        }}
                      />
                    </Box>
                  )}
                </Stack>
              ) : (
                <Box>
                  <Text size="sm" fw={500} mb="xs">
                    Background Color
                  </Text>
                  <Group>
                    <ColorPicker
                      format="hex"
                      value={backgroundColor}
                      onChange={setBackgroundColor}
                      size="sm"
                    />
                    <TextInput
                      value={backgroundColor}
                      onChange={(event) =>
                        setBackgroundColor(event.currentTarget.value)
                      }
                      leftSection={<IconColorPicker size={16} />}
                      style={{ flex: 1 }}
                    />
                  </Group>
                </Box>
              )}

              <Divider my="sm" label="Cloud Settings" labelPosition="left" />

              <Group grow>
                <Box>
                  <Text size="sm" fw={500} mb="xs">
                    Cloud Color
                  </Text>
                  <Text size="xs" c="dimmed" mb="sm">
                    Color of the clouds that display user names
                  </Text>
                  <Group>
                    <ColorPicker
                      format="hex"
                      value={cloudColor}
                      onChange={setCloudColor}
                      size="sm"
                    />
                    <TextInput
                      value={cloudColor}
                      onChange={(event) => setCloudColor(event.currentTarget.value)}
                      leftSection={<IconColorPicker size={16} />}
                      style={{ flex: 1 }}
                    />
                  </Group>
                </Box>

                <Box>
                  <Text size="sm" fw={500} mb="xs">
                    Font Color
                  </Text>
                  <Text size="xs" c="dimmed" mb="sm">
                    Color of the text displayed on clouds
                  </Text>
                  <Group>
                    <ColorPicker
                      format="hex"
                      value={fontColor}
                      onChange={setFontColor}
                      size="sm"
                    />
                    <TextInput
                      value={fontColor}
                      onChange={(event) => setFontColor(event.currentTarget.value)}
                      leftSection={<IconColorPicker size={16} />}
                      style={{ flex: 1 }}
                    />
                  </Group>
                </Box>
              </Group>

              <Divider my="sm" label="Font Settings" labelPosition="left" />

              <Group grow>
                <Select
                  label="Font Family"
                  placeholder="Choose font"
                  value={fontFamily}
                  onChange={setFontFamily}
                  data={[
                    { value: 'Inter', label: 'Inter' },
                    { value: 'Roboto', label: 'Roboto' },
                    { value: 'Montserrat', label: 'Montserrat' },
                    { value: 'Poppins', label: 'Poppins' },
                    { value: 'Open Sans', label: 'Open Sans' },
                    { value: 'Lato', label: 'Lato' },
                    { value: 'Raleway', label: 'Raleway' },
                    { value: 'Playfair Display', label: 'Playfair Display' }
                  ]}
                  styles={{
                    option: {
                      fontFamily: 'var(--option-font-family)',
                    },
                    item: {
                      fontFamily: 'var(--option-font-family)',
                    }
                  }}
                  renderOption={({ option, ...others }) => (
                    <div
                      {...others}
                      style={{
                        fontFamily: option.value,
                        fontSize: '16px',
                        fontWeight: '500'
                      }}
                    >
                      {option.label}
                    </div>
                  )}
                  leftSection={<IconPhoto size={16} />}
                />

                <Select
                  label="Font Size"
                  placeholder="Choose size"
                  value={fontSize}
                  onChange={setFontSize}
                  data={[
                    { value: 'small', label: 'Small (Compact)' },
                    { value: 'medium', label: 'Medium (Standard)' },
                    { value: 'large', label: 'Large (Prominent)' },
                    { value: 'xlarge', label: 'Extra Large (Bold)' }
                  ]}
                  leftSection={<IconPhoto size={16} />}
                />
              </Group>

              <Group>
                <Button
                  leftSection={<IconDeviceFloppy size={16} />}
                  onClick={handleSaveDisplay}
                  loading={displayLoading}
                  color="signature"
                >
                  {displayLoading ? 'Saving...' : 'Save Canvas Settings'}
                </Button>

                <Button
                  variant="outline"
                  leftSection={<IconEye size={16} />}
                  onClick={testPopupOpen ? () => {
                    closeWelcomePopup();
                    setTestPopupOpen(false);
                  } : handleTestWelcomePopup}
                  color={testPopupOpen ? "red" : "signature"}
                >
                  {testPopupOpen ? 'Close Test Window' : 'Test Welcome Canvas'}
                </Button>
              </Group>
            </Stack>
          </Card>
        </Tabs.Panel>

        {/* Camera Settings Tab */}
        <Tabs.Panel value="camera">
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="md">
              <Title order={4}>
                Camera Configuration
              </Title>

              <Select
                label="Select Camera Source"
                placeholder="Choose camera"
                value={selectedCamera}
                onChange={setSelectedCamera}
                data={[
                  // Only show default camera option if cameras are available
                  ...(cameraDevices.length > 0 ? [{ value: 'default', label: 'Default Camera' }] : []),
                  ...cameraDevices.map((device, index) => ({
                    value: `camera_${index}`,
                    label: device.label || `Camera ${index + 1}`
                  })),
                  { value: 'rtsp', label: 'RTSP Stream' }
                ]}
                leftSection={<IconCamera size={16} />}
              />

              {selectedCamera === 'rtsp' && (
                <TextInput
                  label="RTSP URL"
                  placeholder="rtsp://username:password@ip:port/stream"
                  value={rtspUrl}
                  onChange={(event) => setRtspUrl(event.currentTarget.value)}
                  leftSection={<IconCamera size={16} />}
                />
              )}

              <Text size="sm" c="dimmed">
                {cameraDevices.length === 0
                  ? 'No cameras detected or camera permissions denied. Use RTSP stream for external cameras.'
                  : `${cameraDevices.length} camera device${cameraDevices.length !== 1 ? 's' : ''} detected. Select a camera source above to configure for live detection.`
                }
              </Text>

              <Group>
                <Button
                  leftSection={<IconEye size={16} />}
                  onClick={handleTestCamera}
                  variant="outline"
                  loading={cameraLoading}
                  color="signature"
                >
                  {cameraLoading ? 'Testing...' : 'Test Camera'}
                </Button>

                <Button
                  leftSection={<IconDeviceFloppy size={16} />}
                  onClick={handleSaveCamera}
                  loading={cameraLoading}
                  color="signature"
                >
                  {cameraLoading ? 'Saving...' : 'Save Camera Settings'}
                </Button>
              </Group>
            </Stack>
          </Card>
        </Tabs.Panel>

        {/* MediaPipe Face Detection Settings Tab */}
        <Tabs.Panel value="mediapipe">
          <Stack gap="md">
            {/* Quick Presets Section */}
            <Card shadow="sm" p="lg" radius="md" withBorder>
              <Stack gap="md">
                <Title order={4}>
                  <IconRocket size={20} style={{ marginRight: '8px', verticalAlign: 'text-bottom' }} />
                  Quick Presets
                </Title>

                <Text size="sm" c="dimmed">
                  Choose a configuration based on how many people you typically need to detect
                </Text>

                <Group grow>
                  {Object.entries(mediapipePresets).map(([key, preset]) => (
                    <Card
                      key={key}
                      withBorder
                      p="md"
                      style={{
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        ':hover': { backgroundColor: 'rgba(37, 99, 235, 0.05)' }
                      }}
                      onClick={() => !mediapipeLoading && handleApplyPreset(key)}
                    >
                      <Stack gap="xs" align="center">
                        <Text fw={600} size="sm" ta="center">
                          {preset.name || key}
                        </Text>
                        <Text size="xs" c="dimmed" ta="center">
                          {preset.description}
                        </Text>
                        <Button
                          variant="dark"
                          size="xs"
                          color="blue"
                          loading={mediapipeLoading}
                          fullWidth
                        >
                          Apply
                        </Button>
                      </Stack>
                    </Card>
                  ))}
                </Group>
              </Stack>
            </Card>

            {/* Manual Configuration Section */}
            <Card shadow="sm" p="lg" radius="md" withBorder>
              <Stack gap="md">
                <Title order={4}>
                  <IconSettings size={20} style={{ marginRight: '8px', verticalAlign: 'text-bottom' }} />
                  Advanced Manual Configuration
                </Title>

                <Text size="sm" c="black">
                  Fine-tune individual settings for specific requirements. Use presets above for most common scenarios.
                </Text>

                <Group>
                  <Stack gap="xs">
                    <Text size="sm" fw={500}>
                      Maximum number of faces to detect simultaneously
                    </Text>
                    <NumberInput
                      value={mediapipeSettings.max_faces}
                      onChange={(value) =>
                        handleUpdateMediaPipeSettings({ max_faces: value })
                      }
                      min={1}
                      max={50}
                      disabled={mediapipeLoading}
                    />
                  </Stack>
                </Group>

                <Text size="xs" c="dimmed">
                  Using maximum camera resolution with video tracking for best performance
                </Text>

                <Group>
                  <Button
                    leftSection={<IconRocket size={16} />}
                    onClick={handleOptimizeResolution}
                    loading={mediapipeLoading}
                    variant="dark"
                    color="blue"
                  >
                    {mediapipeLoading ? 'Optimizing...' : 'Auto-Optimize Now'}
                  </Button>

                  <Button
                    leftSection={<IconRefresh size={16} />}
                    onClick={loadMediaPipeSettings}
                    loading={mediapipeLoading}
                    variant="dark"
                    color="gray"
                  >
                    Refresh Settings
                  </Button>
                </Group>
              </Stack>
            </Card>

            {/* Performance Monitor Section */}
            <Card shadow="sm" p="lg" radius="md" withBorder>
              <Stack gap="md">
                <Title order={4}>
                  <IconInfoCircle size={20} style={{ marginRight: '8px', verticalAlign: 'text-bottom' }} />
                  Performance Monitor
                </Title>

                <Group grow>
                  <Box>
                    <Text size="lg" fw={700} c="blue">
                      {mediapipePerformance.avg_detection_time_ms?.toFixed(1) || 'N/A'}ms
                    </Text>
                    <Text size="sm" c="dimmed">
                      Average Detection Time
                    </Text>
                  </Box>

                  <Box>
                    <Text size="lg" fw={700} c="green">
                      {mediapipePerformance.registered_faces || 0}
                    </Text>
                    <Text size="sm" c="dimmed">
                      Registered Faces
                    </Text>
                  </Box>

                  <Box>
                    <Text size="lg" fw={700} c="orange">
                      {mediapipePerformance.total_detections || 0}
                    </Text>
                    <Text size="sm" c="dimmed">
                      Total Detections
                    </Text>
                  </Box>
                </Group>

                <Alert color="blue" title="Performance Guidelines">
                  <Text size="sm">
                    • VGA (640x480): 8 faces max for 30fps<br/>
                    • HD (1280x720): 15 faces max for 30fps<br/>
                    • Full HD (1920x1080): 25 faces max for 30fps<br/>
                    • 4K+ resolutions: 40+ faces possible with good hardware
                    {mediapipeSettings.include_landmarks && (
                      <>
                        <br/>
                        • 📍 <strong>Landmark Mode Active:</strong> Sending 468 points per face
                      </>
                    )}
                  </Text>
                </Alert>
              </Stack>
            </Card>
          </Stack>
        </Tabs.Panel>

        {/* Data Management Tab */}
        <Tabs.Panel value="data">
          <Stack gap="md">
            {/* People List Section */}
            <Card shadow="sm" p="lg" radius="md" withBorder>
              <Stack gap="md">
                <Flex justify="space-between" align="center">
                  <Title order={4}>
                    <IconUsersGroup size={20} style={{ marginRight: '8px', verticalAlign: 'text-bottom' }} />
                    Registered People ({people.length})
                  </Title>
                  <Button
                    leftSection={<IconRefresh size={16} />}
                    onClick={loadPeopleData}
                    loading={peopleLoading}
                    variant="filled"
                    size="sm"
                    color="blue"
                    styles={{
                      root: {
                        backgroundColor: '#228be6',
                        color: 'white',
                        '&:hover': {
                          backgroundColor: '#1c7ed6'
                        }
                      }
                    }}
                  >
                    Refresh
                  </Button>
                </Flex>

                <ScrollArea h={400} style={{ position: 'relative' }}>
                  <LoadingOverlay visible={peopleLoading} overlayProps={{ blur: 2 }} />

                  {people.length === 0 ? (
                    <Text c="dimmed" ta="center" py="xl">
                      No people registered yet
                    </Text>
                  ) : (
                    <Stack gap="xs">
                      {people.map((person) => (
                        <Card key={person.id} withBorder p="md">
                          <Group justify="space-between" align="center">
                            <Group>
                              {person.has_image ? (
                                <Image
                                  src={`${person.image_path}`}
                                  alt={`${person.name} reference photo`}
                                  w={60}
                                  h={60}
                                  radius="md"
                                  style={{ objectFit: 'cover' }}
                                  fallbackSrc="data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' width='60' height='60' viewBox='0 0 24 24' fill='%23868e96'%3e%3cpath d='M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z'/%3e%3c/svg%3e"
                                />
                              ) : (
                                <Box
                                  w={60}
                                  h={60}
                                  style={{
                                    backgroundColor: '#f8f9fa',
                                    borderRadius: '6px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    border: '1px solid #dee2e6'
                                  }}
                                >
                                  <IconUser size={30} color="#868e96" />
                                </Box>
                              )}

                              <Stack gap={0}>
                                <Text fw={500} size="sm">
                                  {person.name}
                                </Text>
                                <Text size="xs" c="dimmed">
                                  ID: {person.id}
                                </Text>
                                {person.title && (
                                  <Text size="xs" c="blue.6">
                                    {person.title}
                                  </Text>
                                )}

                                {/* Photo Information */}
                                <Group gap={4} mt={4}>
                                  <Badge
                                    size="xs"
                                    variant="dark"
                                    color={person.total_photos > 1 ? "green" : "blue"}
                                    leftSection={<IconPhoto size={10} />}
                                  >
                                    {person.total_photos} photo{person.total_photos !== 1 ? 's' : ''} {person.additional_photos_count > 0 && (
                                    <Badge
                                      size="xs"
                                      variant="dark"
                                      color="orange"
                                    >
                                      +{person.additional_photos_count} additional
                                    </Badge>
                                  )}
                                  </Badge>

                                  
                                </Group>
                              </Stack>
                            </Group>

                            <Stack gap="xs">
                              {/* Add Photo Upload */}
                              <FileInput
                                placeholder="Add photo"
                                accept="image/*"
                                size="xs"
                                leftSection={<IconUpload size={12} />}
                                onChange={(file) => handleUploadAdditionalPhoto(person.id, person.name, file)}
                                disabled={uploadingPhotos[person.id]}
                                styles={{
                                  input: {
                                    fontSize: '11px',
                                    height: '28px',
                                    backgroundColor: 'rgba(0, 36, 61, 0.05)',
                                    border: '1px solid rgba(0, 36, 61, 0.2)',
                                    '&:hover': {
                                      backgroundColor: 'rgba(0, 36, 61, 0.1)',
                                    },
                                  },
                                }}
                              />

                              <Button
                                leftSection={<IconTrash size={14} />}
                                onClick={() => handleDeletePerson(person.id, person.name)}
                                color="red"
                                variant="filled"
                                size="xs"
                                styles={{
                                  root: {
                                    backgroundColor: '#fa5252',
                                    color: 'white',
                                    fontSize: '12px',
                                    fontWeight: 500,
                                    '&:hover': {
                                      backgroundColor: '#e03131'
                                    }
                                  }
                                }}
                              >
                                Delete
                              </Button>
                            </Stack>
                          </Group>
                        </Card>
                      ))}
                    </Stack>
                  )}
                </ScrollArea>
              </Stack>
            </Card>

            {/* Bulk Actions Section */}
            <Card shadow="sm" p="lg" radius="md" withBorder>
              <Stack gap="md">
                <Title order={4}>
                  Bulk Actions
                </Title>

                <Alert color="red" title="Warning" icon={<IconTrash size={16} />}>
                  This action cannot be undone. All registered people data will be
                  permanently deleted.
                </Alert>

                <Button
                  leftSection={<IconTrash size={16} />}
                  onClick={handleDeleteAllPeople}
                  loading={deleteLoading}
                  color="red"
                  variant="filled"
                  disabled={people.length === 0}
                  size="md"
                  styles={{
                    root: {
                      backgroundColor: people.length === 0 ? '#ced4da' : '#fa5252',
                      color: people.length === 0 ? '#868e96' : 'white',
                      fontWeight: 600,
                      fontSize: '14px',
                      '&:hover': people.length > 0 ? {
                        backgroundColor: '#e03131'
                      } : {}
                    }
                  }}
                >
                  {deleteLoading ? 'Deleting...' : `Delete All People (${people.length})`}
                </Button>
              </Stack>
            </Card>
          </Stack>
        </Tabs.Panel>
      </Tabs>
      </Box>
    </Box>
  );
}