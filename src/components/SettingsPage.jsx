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
} from '@mantine/core';
import {
  IconSettings,
  IconUser,
  IconLock,
  IconClock,
  IconCamera,
  IconDeviceFloppy,
  IconColorPicker,
  IconPalette,
  IconEye,
  IconTrash,
} from '@tabler/icons-react';
import apiService, { webcamUtils } from '../services/api';
import { testWelcomePopup, closeWelcomePopup, isWelcomePopupOpen } from '../services/welcomePopup';

export function SettingsPage({ onSaveSettings }) {
  // Admin settings state
  const [oldAdminId, setOldAdminId] = useState('');
  const [oldAdminPass, setOldAdminPass] = useState('');
  const [newAdminId, setNewAdminId] = useState('');
  const [newAdminPass, setNewAdminPass] = useState('');
  const [newAdminPassConf, setNewAdminPassConf] = useState('');

  // Display settings state
  const [displayTimer, setDisplayTimer] = useState(5);
  const [backgroundColor, setBackgroundColor] = useState('#E1EBFF');
  const [fontColor, setFontColor] = useState('#00243D');

  // Camera settings state
  const [cameraUrl, setCameraUrl] = useState('');
  const [cameraStatus, setCameraStatus] = useState('Not Connected');
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

  // Load available cameras on component mount
  useEffect(() => {
    const loadCameras = async () => {
      try {
        const devices = await webcamUtils.getVideoDevices();
        setCameraDevices(devices);
        if (devices.length > 0 && selectedCamera === 'default') {
          setSelectedCamera(devices[0].deviceId);
        }
      } catch (error) {
        console.error('Error loading cameras:', error);
      }
    };
    loadCameras();
  }, [selectedCamera]);

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

  const handleSaveDisplay = () => {
    const settings = {
      timer: displayTimer,
      backgroundColor,
      fontColor,
    };

    // Save to localStorage for welcome popup access
    localStorage.setItem('faceRecognitionDisplaySettings', JSON.stringify(settings));

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
  };

  const handleTestWelcomePopup = () => {
    const currentSettings = {
      backgroundColor,
      fontColor,
      timer: displayTimer
    };
    testWelcomePopup(currentSettings);
    setTestPopupOpen(true);
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
    setCameraStatus('Testing...');
    setError('');

    try {
      const result = await apiService.testCamera(selectedCamera === 'rtsp' ? rtspUrl : cameraUrl);

      if (result.success) {
        setCameraStatus('Connected');
        setSuccess('Camera test successful!');
      } else {
        setCameraStatus('Not Connected');
        setError(result.message || 'Camera test failed');
      }
    } catch (error) {
      setCameraStatus('Not Connected');
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
      const urlToSave = selectedCamera === 'rtsp' ? rtspUrl : cameraUrl;
      const result = await apiService.updateCameraSettings(urlToSave);

      if (result.success) {
        setSuccess('Camera settings saved successfully!');
        onSaveSettings?.({
          type: 'camera',
          url: urlToSave,
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
      const students = await apiService.getStudents();

      if (students.success && students.students) {
        const deletePromises = students.students.map(student =>
          apiService.deleteStudent(student.student_id)
        );

        await Promise.all(deletePromises);
        setSuccess('All student records deleted successfully!');

        onSaveSettings?.({
          type: 'deleteStudents',
        });
      } else {
        setError('Failed to retrieve student list');
      }
    } catch (error) {
      setError('Failed to delete student records: ' + error.message);
      console.error('Delete students error:', error);
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <Box style={{ width: '100%', minHeight: '100%' }}>
      <Box style={{ padding: '24px' }}>
        <Title order={2} ta="center" c="rgb(0, 36, 61)" mb="xl">
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

      <Tabs defaultValue="admin" variant="pills">
        <Tabs.List grow mb="md">
          <Tabs.Tab value="admin" leftSection={<IconUser size={16} />}>
            Admin Settings
          </Tabs.Tab>
          <Tabs.Tab value="display" leftSection={<IconPalette size={16} />}>
            Display Settings
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
              <Title order={4} c="rgb(0, 36, 61)">
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
                style={{ backgroundColor: 'rgb(0, 36, 61)' }}
              >
                {adminLoading ? 'Changing...' : 'Change Admin'}
              </Button>
            </Stack>
          </Card>
        </Tabs.Panel>

        {/* Display Settings Tab */}
        <Tabs.Panel value="display">
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="md">
              <Title order={4} c="rgb(0, 36, 61)">
                Display Preferences
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

              <Group>
                <Button
                  leftSection={<IconDeviceFloppy size={16} />}
                  onClick={handleSaveDisplay}
                  loading={displayLoading}
                  style={{ backgroundColor: 'rgb(0, 36, 61)' }}
                >
                  {displayLoading ? 'Saving...' : 'Save Display Settings'}
                </Button>

                <Button
                  variant="outline"
                  leftSection={<IconEye size={16} />}
                  onClick={testPopupOpen ? () => {
                    closeWelcomePopup();
                    setTestPopupOpen(false);
                  } : handleTestWelcomePopup}
                  style={{
                    borderColor: testPopupOpen ? 'rgb(255, 107, 107)' : 'rgb(0, 36, 61)',
                    color: testPopupOpen ? 'rgb(255, 107, 107)' : 'rgb(0, 36, 61)'
                  }}
                >
                  {testPopupOpen ? 'Close Test Window' : 'Test Welcome Screen'}
                </Button>
              </Group>
            </Stack>
          </Card>
        </Tabs.Panel>

        {/* Camera Settings Tab */}
        <Tabs.Panel value="camera">
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="md">
              <Title order={4} c="rgb(0, 36, 61)">
                Camera Configuration
              </Title>

              <Select
                label="Select Camera Source"
                placeholder="Choose camera"
                value={selectedCamera}
                onChange={setSelectedCamera}
                data={[
                  { value: 'default', label: 'Default Camera' },
                  ...cameraDevices.map(device => ({
                    value: device.deviceId,
                    label: device.label || `Camera ${device.deviceId.substring(0, 8)}...`
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

              <TextInput
                label="Camera RTSP URL (Legacy)"
                placeholder="rtsp://camera-url:port/stream"
                value={cameraUrl}
                onChange={(event) => setCameraUrl(event.currentTarget.value)}
                leftSection={<IconCamera size={16} />}
                description="This field is for backward compatibility"
              />

              <Alert
                color={cameraStatus === 'Connected' ? 'green' : 'orange'}
                title={`Camera Status: ${cameraStatus}`}
                icon={<IconCamera size={16} />}
              >
                {cameraStatus === 'Connected'
                  ? 'Camera is working properly'
                  : 'Camera not connected or URL invalid'}
              </Alert>

              <Text size="sm" c="rgb(0, 36, 61)">
                {cameraDevices.length} camera(s) detected. Select a camera source above to configure for live detection.
              </Text>

              <Group>
                <Button
                  leftSection={<IconEye size={16} />}
                  onClick={handleTestCamera}
                  variant="outline"
                  loading={cameraLoading}
                  style={{ borderColor: 'rgb(0, 36, 61)', color: 'rgb(0, 36, 61)' }}
                >
                  {cameraLoading ? 'Testing...' : 'Test Camera'}
                </Button>

                <Button
                  leftSection={<IconDeviceFloppy size={16} />}
                  onClick={handleSaveCamera}
                  loading={cameraLoading}
                  style={{ backgroundColor: 'rgb(0, 36, 61)' }}
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
              <Title order={4} c="rgb(0, 36, 61)">
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
                {deleteLoading ? 'Deleting...' : 'Delete All Students'}
              </Button>
            </Stack>
          </Card>
        </Tabs.Panel>
      </Tabs>
      </Box>
    </Box>
  );
}