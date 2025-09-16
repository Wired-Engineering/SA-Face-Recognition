import { useState, useEffect } from 'react';
import {
  Paper,
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
} from '@tabler/icons-react';
import apiService, { webcamUtils } from '../services/api';
import { testWelcomePopup, closeWelcomePopup, isWelcomePopupOpen } from '../services/welcomePopup';

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
  const [useBackgroundImage, setUseBackgroundImage] = useState(false);
  const [backgroundImagePreview, setBackgroundImagePreview] = useState(null);
  const [fontFamily, setFontFamily] = useState('Inter');
  const [fontSize, setFontSize] = useState('medium');

  // Camera settings state
  const [cameraDevices, setCameraDevices] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('default');
  const [rtspUrl, setRtspUrl] = useState('');

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

        // Load saved camera settings from backend
        const cameraSettings = await apiService.getCameraSettings();
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

        // Load Canvas Settings from backend
        const displaySettings = await apiService.getDisplaySettings();
        if (displaySettings.success) {
          setDisplayTimer(displaySettings.timer || 5);
          setBackgroundColor(displaySettings.background_color || theme.colors.accent[1]);
          setFontColor(displaySettings.font_color || theme.other.signatureNavy);
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
      } catch (error) {
        console.error('Error loading settings:', error);
      }
    };
    loadCamerasAndSettings();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
        useBackgroundImage,
        null, // Don't send image data
        fontFamily,
        fontSize
      );

      if (result.success) {
        // Also save to localStorage for welcome popup access
        localStorage.setItem('faceRecognitionDisplaySettings', JSON.stringify(settings));

        setSuccess('Canvas Settings saved successfully!');

        // If test popup is open, close and reopen with new saved settings
        if (testPopupOpen && isWelcomePopupOpen()) {
          console.log('💾 Settings saved, updating test popup');
          closeWelcomePopup();
          setTimeout(() => {
            testWelcomePopup(settings);
          }, 100);
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
        setSuccess('Background image uploaded successfully!');
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
      // Determine the source and parameters for testing
      let source = selectedCamera;
      let deviceId = null;
      let rtspUrlToTest = null;

      if (selectedCamera === 'rtsp') {
        source = 'rtsp';
        rtspUrlToTest = rtspUrl;
        // Validate RTSP URL before testing
        if (!rtspUrl || rtspUrl.trim() === '') {
          setError('Please enter an RTSP URL before testing');
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
          console.log(`Testing camera ${cameraIndex}: device ID = ${deviceId}`);
        } else {
          setError('Selected camera not found in available devices');
          return;
        }
      } else {
        // Fallback to default
        source = 'default';
      }

      const result = await apiService.testCamera(source, deviceId, rtspUrlToTest);

      if (result.success) {
        setSuccess('Camera test successful!');
      } else {
        setError(result.message || 'Camera test failed');
      }
    } catch (error) {
      setError('Camera test failed: ' + error.message);
      console.error('Camera test error:', error);
    } finally {
      setCameraLoading(false);
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

  const handleDeleteStudent = async () => {
    if (!window.confirm('Are you sure you want to delete all student records? This action cannot be undone.')) {
      return;
    }

    setDeleteLoading(true);
    setError('');
    setSuccess('');

    try {
      // Note: This endpoint may not exist in the current API, but we'll call it anyway
      // The backend should implement a bulk delete endpoint
      const people = await apiService.getpeople();

      if (people.success && people.people) {
        const deletePromises = people.people.map(student =>
          apiService.deleteStudent(student.student_id)
        );

        await Promise.all(deletePromises);
        setSuccess('All student records deleted successfully!');

        onSaveSettings?.({
          type: 'deletepeople',
        });
      } else {
        setError('Failed to retrieve student list');
      }
    } catch (error) {
      setError('Failed to delete student records: ' + error.message);
      console.error('Delete people error:', error);
    } finally {
      setDeleteLoading(false);
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
                label="Set Display Timer (seconds)"
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
                        variant="outline"
                        color="red"
                        onClick={handleDeleteBackgroundImage}
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
                <Group grow>
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

                <Box>
                  <Text size="sm" fw={500} mb="xs">
                    Font Color
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
              )}

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
                  { value: 'default', label: 'Default Camera' },
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
                {cameraDevices.length} camera device{cameraDevices.length !== 1 ? 's' : ''} detected. Select a camera source above to configure for live detection.
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

        {/* Data Management Tab */}
        <Tabs.Panel value="data">
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="md">
              <Title order={4}>
                Data Management
              </Title>

              <Alert color="red" title="Warning" icon={<IconTrash size={16} />}>
                This action cannot be undone. All registered student data will be
                permanently deleted.
              </Alert>

              <Button
                leftSection={<IconTrash size={16} />}
                onClick={handleDeleteStudent}
                loading={deleteLoading}
                color="red"
                variant="filled"
              >
                {deleteLoading ? 'Deleting...' : 'Delete All people'}
              </Button>
            </Stack>
          </Card>
        </Tabs.Panel>
      </Tabs>
      </Box>
    </Box>
  );
}