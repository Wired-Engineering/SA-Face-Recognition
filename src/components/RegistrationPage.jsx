import { useState, useRef, useEffect } from 'react';
import {
  Paper,
  Stack,
  Title,
  TextInput,
  Button,
  Group,
  Image,
  Box,
  Text,
  FileInput,
  Alert,
  Divider,
  List,
  ThemeIcon,
  Badge,
  Collapse,
  ScrollArea,
  ActionIcon,
  Progress,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconUser, IconCamera, IconUpload, IconUserPlus, IconAlertCircle, IconCheck, IconPhoto, IconSun, IconEye, IconFileUpload, IconInfoCircle, IconUserCheck, IconUserX, IconUserOff, IconChevronDown, IconChevronUp, IconDownload } from '@tabler/icons-react';
import apiService, { imageUtils, webcamUtils } from '../services/api';

export function RegistrationPage({ onRegister }) {
  const [personName, setpersonName] = useState('');
  const [personTitle, setpersonTitle] = useState('');
  const [personRegistration, setpersonRegistration] = useState('');
  const [photoFile, setPhotoFile] = useState(null);
  const [csvFile, setCsvFile] = useState(null);
  const [capturedPhoto, setCapturedPhoto] = useState(null);
  const [isCapturing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [stream, setStream] = useState(null);
  const [opened, { open, close }] = useDisclosure(false);
  const [cameraSettings, setCameraSettings] = useState(null);
  const [photoFileUrl, setPhotoFileUrl] = useState(null);

  // Additional photos state
  const [registeredPersonId, setRegisteredPersonId] = useState(null);
  const [additionalPhotos, setAdditionalPhotos] = useState([]);
  const [additionalPhotoLoading, setAdditionalPhotoLoading] = useState(false);
  const [additionalPhotoError, setAdditionalPhotoError] = useState('');
  const [additionalPhotoSuccess, setAdditionalPhotoSuccess] = useState('');
  const [additionalCaptureOpened, { open: openAdditionalCapture, close: closeAdditionalCapture }] = useDisclosure(false);
  const [additionalStream, setAdditionalStream] = useState(null);
  const additionalVideoRef = useRef(null);

  // CSV Upload state
  const [csvLoading, setCsvLoading] = useState(false);
  const [csvResults, setCsvResults] = useState(null);
  const [showCsvDetails, setShowCsvDetails] = useState(false);
  const [csvRequirements, setCsvRequirements] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [uploadMessage, setUploadMessage] = useState('');

  const videoRef = useRef(null);
  const additionalPhotosRef = useRef(null);

  // Fetch camera settings and CSV requirements on component mount
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        // Fetch camera settings
        const settings = await apiService.getCameraSettings();
        if (settings.success) {
          setCameraSettings(settings);
        }
      } catch (error) {
        console.error('Failed to fetch camera settings:', error);
        // Use default settings if fetch fails
        setCameraSettings({ source: 'default', device_id: null, rtsp_url: null });
      }

      try {
        // Fetch CSV requirements
        const requirements = await apiService.getCSVRequirements();
        if (requirements.success) {
          setCsvRequirements(requirements);
        }
      } catch (error) {
        console.error('Failed to fetch CSV requirements:', error);
      }
    };

    fetchInitialData();
  }, []);

  // Handle photo file URL creation and cleanup
  useEffect(() => {
    if (photoFile) {
      const url = URL.createObjectURL(photoFile);
      setPhotoFileUrl(url);

      // Cleanup function to revoke the blob URL
      return () => {
        URL.revokeObjectURL(url);
        setPhotoFileUrl(null);
      };
    } else {
      setPhotoFileUrl(null);
    }
  }, [photoFile]);


  const handleStartCapture = async () => {
    try {
      open();

      // Use configured camera settings
      let mediaStream;
      if (cameraSettings && cameraSettings.source === 'rtsp' && cameraSettings.rtsp_url) {
        // For RTSP cameras, we can't use getUserMedia directly
        // This would need a different implementation, possibly using a video element with the RTSP stream
        setError('RTSP camera capture is not yet supported in registration. Please use file upload instead.');
        close();
        return;
      } else {
        // Use webcam with configured device ID if available
        const constraints = {};
        if (cameraSettings && cameraSettings.device_id) {
          constraints.video = {
            deviceId: { exact: cameraSettings.device_id },
            width: { ideal: 1280 },
            height: { ideal: 720 },
            frameRate: { ideal: 30 },
          };
        }

        mediaStream = await webcamUtils.getUserMedia(constraints);
      }

      setStream(mediaStream);
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
    } catch (error) {
      setError('Failed to access camera: ' + error.message);
      close();
    }
  };

  const handleCapturePhoto = () => {
    if (videoRef.current) {
      const imageData = imageUtils.captureFromVideo(videoRef.current);
      setCapturedPhoto(imageData);
      setPhotoFile(null);
      setPhotoFileUrl(null);
      handleStopCapture();
    }
  };

  const handleCSVUpload = async () => {
    if (!csvFile) {
      setError('Please select a CSV file');
      return;
    }

    setCsvLoading(true);
    setError('');
    setCsvResults(null);
    setUploadProgress(0);
    setUploadMessage('Uploading CSV file...');

    try {
      // Use streaming API for real-time progress updates
      apiService.uploadCSVStream(
        csvFile,
        // onProgress callback
        (progressData) => {
          setUploadProgress(progressData.percentage || 0);
          setUploadMessage(progressData.message || 'Processing...');
        },
        // onComplete callback
        (completeData) => {
          setUploadProgress(100);
          setUploadMessage('Complete!');

          if (completeData.success) {
            setCsvResults(completeData);
            setSuccess(`CSV processed: ${completeData.successful_registrations} registered, ${completeData.failed_registrations} failed, ${completeData.skipped_no_image} skipped`);

            // Reset CSV file after successful upload
            setCsvFile(null);

            // Call parent callback if provided
            if (completeData.successful_registrations > 0 && onRegister) {
              onRegister({
                type: 'bulk',
                count: completeData.successful_registrations
              });
            }
          } else {
            setError(completeData.error || 'Failed to process CSV');
          }

          setTimeout(() => {
            setCsvLoading(false);
            setUploadProgress(null);
            setUploadMessage('');
          }, 1000);
        },
        // onError callback
        (errorData) => {
          setError(`Failed to upload CSV: ${errorData.error || 'Unknown error'}`);
          setCsvLoading(false);
          setUploadProgress(null);
          setUploadMessage('');
        }
      );
    } catch (error) {
      setError(`Failed to upload CSV: ${error.message}`);
      setCsvLoading(false);
      setUploadProgress(null);
      setUploadMessage('');
    }
  };

  const downloadFailedUsersCSV = () => {
    if (!csvResults || !csvResults.details) return;

    const { failed, skipped } = csvResults.details;
    const allFailed = [...(failed || []), ...(skipped || [])];

    if (allFailed.length === 0) return;

    // Create CSV content
    const headers = ['Row Number', 'Name', 'Title', 'Registration Number', 'Error/Reason'];
    const rows = allFailed.map(user => [
      user.row_number || '',
      user.name || '',
      user.title || '',
      user.registration_number || '',
      user.error || user.reason || ''
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');

    // Create download link
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);

    link.setAttribute('href', url);
    link.setAttribute('download', `failed_registrations_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleStopCapture = () => {
    if (stream) {
      webcamUtils.stopStream(stream);
      setStream(null);
    }
    close();
  };

  const handleRegister = async () => {
    if (!personName || !personTitle || !personRegistration || (!photoFile && !capturedPhoto)) {
      setError('Please fill in all fields and provide a photo');
      return;
    }

    setLoading(true);
    setError('');
    setSuccess('');

    try {
      let imageData;

      if (photoFile) {
        // Validate file
        imageUtils.validateImageFile(photoFile);
        imageData = await imageUtils.fileToBase64(photoFile);
      } else if (capturedPhoto) {
        imageData = capturedPhoto;
      }

      const result = await apiService.registerperson(personName, personTitle, personRegistration, imageData);

      if (result.success) {
        setSuccess(`Person ${personName} registered successfully! ID: ${result.person_id}`);
        setRegisteredPersonId(result.person_id);

        // Don't reset form immediately - let user add more photos
        // Reset form later when they're done with additional photos

        // Call parent callback if provided
        onRegister?.({
          id: result.person_id,
          name: personName,
          title: personTitle,
          registration: personRegistration,
          photo: imageData,
        });

        // Scroll to additional photos section after a short delay
        setTimeout(() => {
          additionalPhotosRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 300);
      } else {
        setError(result.message || 'Registration failed');
      }
    } catch (error) {
      setError('Registration failed: ' + error.message);
      console.error('Registration error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddAdditionalPhoto = async (file, capturedImageData = null) => {
    if (!registeredPersonId || (!file && !capturedImageData)) {
      setAdditionalPhotoError('No person registered or no image provided');
      return;
    }

    setAdditionalPhotoLoading(true);
    setAdditionalPhotoError('');
    setAdditionalPhotoSuccess('');

    try {
      let imageData;
      let imageUrl;

      if (file) {
        // Validate file
        imageUtils.validateImageFile(file);
        imageData = await imageUtils.fileToBase64(file);
        imageUrl = URL.createObjectURL(file);
      } else if (capturedImageData) {
        imageData = capturedImageData;
        imageUrl = capturedImageData;
      }

      const result = await apiService.addAdditionalPhoto(registeredPersonId, imageData);

      if (result.success) {
        setAdditionalPhotoSuccess(`Additional photo added successfully!`);
        setAdditionalPhotos(prev => [...prev, {
          file: file || null,
          url: imageUrl,
          captured: !!capturedImageData
        }]);

        // Clear success message after 3 seconds
        setTimeout(() => setAdditionalPhotoSuccess(''), 3000);
      } else {
        setAdditionalPhotoError(result.message || 'Failed to add additional photo');
      }
    } catch (error) {
      setAdditionalPhotoError('Failed to add additional photo: ' + error.message);
      console.error('Additional photo error:', error);
    } finally {
      setAdditionalPhotoLoading(false);
    }
  };

  const handleStartAdditionalCapture = async () => {
    try {
      openAdditionalCapture();

      // Use configured camera settings
      let mediaStream;
      if (cameraSettings && cameraSettings.source === 'rtsp' && cameraSettings.rtsp_url) {
        setAdditionalPhotoError('RTSP camera capture is not yet supported. Please use file upload instead.');
        closeAdditionalCapture();
        return;
      } else {
        // Use webcam with configured device ID if available
        const constraints = {};
        if (cameraSettings && cameraSettings.device_id) {
          constraints.video = {
            deviceId: { exact: cameraSettings.device_id },
            width: { ideal: 1280 },
            height: { ideal: 720 },
            frameRate: { ideal: 30 },
          };
        }

        mediaStream = await webcamUtils.getUserMedia(constraints);
      }

      setAdditionalStream(mediaStream);
      if (additionalVideoRef.current) {
        additionalVideoRef.current.srcObject = mediaStream;
      }
    } catch (error) {
      setAdditionalPhotoError('Failed to access camera: ' + error.message);
      closeAdditionalCapture();
    }
  };

  const handleCaptureAdditionalPhoto = () => {
    if (additionalVideoRef.current) {
      const imageData = imageUtils.captureFromVideo(additionalVideoRef.current);
      handleAddAdditionalPhoto(null, imageData);
      handleStopAdditionalCapture();
    }
  };

  const handleStopAdditionalCapture = () => {
    if (additionalStream) {
      webcamUtils.stopStream(additionalStream);
      setAdditionalStream(null);
    }
    closeAdditionalCapture();
  };

  const handleStartOver = () => {
    // Reset all form state
    setpersonName('');
    setpersonTitle('');
    setpersonRegistration('');
    setPhotoFile(null);
    setPhotoFileUrl(null);
    setCapturedPhoto(null);
    setRegisteredPersonId(null);
    setAdditionalPhotos([]);
    setError('');
    setSuccess('');
    setAdditionalPhotoError('');
    setAdditionalPhotoSuccess('');

    // Clean up additional photo URLs
    additionalPhotos.forEach(photo => {
      if (photo.url) URL.revokeObjectURL(photo.url);
    });
  };

  return (
    <Box style={{ width: '100%', minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Stack gap="xl" style={{ width: '600px', maxWidth: '100%' }}>
        {/* Header */}
        <Box ta="center" mb="md">
          <Title order={2} mb="xs">
            Person Registration
          </Title>
        </Box>

        {/* Registration Form */}
        <Paper
          shadow="md"
          p="xl"
          radius="md"
          style={{
            backgroundColor: 'white',
            width: '100%',
          }}
        >
          <Stack gap="md">
            <Title order={3} ta="center" mb="md">
              Register New Person
            </Title>

            {/* CSV Upload Section */}
            <Box>
              <Group justify="space-between" mb="xs">
                <Text size="sm" fw={700}>
                  Bulk Registration via CSV
                </Text>
                {csvRequirements && (
                  <ActionIcon
                    variant="subtle"
                    onClick={() => setShowCsvDetails(!showCsvDetails)}
                    title="CSV Requirements"
                  >
                    {showCsvDetails ? <IconChevronUp size={16} /> : <IconChevronDown size={16} />}
                  </ActionIcon>
                )}
              </Group>

              <Collapse in={showCsvDetails}>
                <Alert
                  icon={<IconInfoCircle size={16} />}
                  color="blue"
                  mb="md"
                >
                  <Text size="sm" fw={500} mb="xs">Required CSV Columns:</Text>
                  <List size="sm" spacing="xs">
                    {csvRequirements?.required_columns?.map((col) => (
                      <List.Item key={col}>{col}</List.Item>
                    ))}
                  </List>
                  <Text size="xs" c="dimmed" mt="xs">
                    Note: Users without valid Image URLs will be skipped
                  </Text>
                </Alert>
              </Collapse>

              <Group grow>
                <FileInput
                  leftSection={<IconFileUpload size={16} />}
                  placeholder="Select CSV file"
                  accept=".csv"
                  value={csvFile}
                  onChange={setCsvFile}
                  disabled={csvLoading}
                  styles={{
                    input: {
                      backgroundColor: 'white',
                      border: '1px solid rgb(206, 212, 218)',
                      '&:focus': {
                        borderColor: 'rgb(0, 36, 61)',
                        outline: '2px solid rgb(0, 36, 61)',
                        outlineOffset: '2px',
                      },
                    },
                  }}
                />
                <Button
                  leftSection={<IconUpload size={16} />}
                  onClick={handleCSVUpload}
                  loading={csvLoading}
                  disabled={!csvFile || csvLoading}
                  color="signature"
                >
                  Process CSV
                </Button>
              </Group>

              {/* Upload Progress */}
              {csvLoading && (
                <Box mt="md">
                  <Text size="sm" mb="xs">{uploadMessage || 'Processing CSV...'}</Text>
                  <Progress
                    value={uploadProgress || 0}
                    animated
                    striped
                    size="lg"
                  />
                </Box>
              )}

              {/* CSV Upload Results */}
              {csvResults && (
                <Box mt="md">
                  <Group justify="center" gap="md" mb="md">
                    <Badge
                      size="lg"
                      color="green"
                      leftSection={<IconUserCheck size={14} />}
                    >
                      {csvResults.successful_registrations} Registered
                    </Badge>
                    {csvResults.failed_registrations > 0 && (
                      <Badge
                        size="lg"
                        color="red"
                        leftSection={<IconUserX size={14} />}
                      >
                        {csvResults.failed_registrations} Failed
                      </Badge>
                    )}
                    {csvResults.skipped_no_image > 0 && (
                      <Badge
                        size="lg"
                        color="orange"
                        leftSection={<IconUserOff size={14} />}
                      >
                        {csvResults.skipped_no_image} Skipped
                      </Badge>
                    )}
                  </Group>

                  {/* Download Failed Users Button */}
                  {(csvResults.details?.failed?.length > 0 || csvResults.details?.skipped?.length > 0) && (
                    <Group justify="center" mb="md">
                      <Button
                        leftSection={<IconDownload size={16} />}
                        onClick={downloadFailedUsersCSV}
                        variant="outline"
                        color="signature"
                      >
                        Download Failed/Skipped Users CSV
                      </Button>
                    </Group>
                  )}

                  {/* Show details of skipped users */}
                  {csvResults.details?.skipped?.length > 0 && (
                    <Alert
                      color="orange"
                      title="Users Skipped"
                      mb="md"
                    >
                      <ScrollArea h={100}>
                        <List size="xs" spacing="xs">
                          {csvResults.details.skipped.map((user) => (
                            <List.Item key={user.row_number}>
                              Row {user.row_number}: {user.name} ({user.title})
                              {user.reason && <Text size="xs" c="dimmed"> - {user.reason}</Text>}
                            </List.Item>
                          ))}
                        </List>
                      </ScrollArea>
                    </Alert>
                  )}

                  {/* Show failed registrations */}
                  {csvResults.details?.failed?.length > 0 && (
                    <Alert
                      color="red"
                      title="Failed Registrations"
                      mb="md"
                    >
                      <ScrollArea h={100}>
                        <List size="xs" spacing="xs">
                          {csvResults.details.failed.map((user) => (
                            <List.Item key={user.row_number}>
                              Row {user.row_number}: {user.name} ({user.title})
                              {user.reason && <Text size="xs" c="dimmed"> - {user.reason}</Text>}
                              {user.error && <Text size="xs" c="dimmed"> - {user.error}</Text>}
                            </List.Item>
                          ))}
                        </List>
                      </ScrollArea>
                    </Alert>
                  )}
                </Box>
              )}
            </Box>

            <Divider my="xl" label="OR" labelPosition="center" />

            {/* Manual Person Information */}

            <TextInput
              leftSection={<IconUser size={16} />}
              label="Name"
              placeholder="Enter name here"
              value={personName}
              onChange={(event) => setpersonName(event.currentTarget.value)}
              required
              styles={{
                input: {
                  backgroundColor: 'white',
                  border: '1px solid rgb(206, 212, 218)',
                  '&:focus': {
                    borderColor: 'rgb(0, 36, 61)',
                    outline: '2px solid rgb(0, 36, 61)',
                    outlineOffset: '2px',
                  },
                },
              }}
            />

            <TextInput
              leftSection={<IconUser size={16} />}
              label="Title"
              placeholder="Enter title here"
              value={personTitle}
              onChange={(event) => setpersonTitle(event.currentTarget.value)}
              required
              styles={{
                input: {
                  backgroundColor: 'white',
                  border: '1px solid rgb(206, 212, 218)',
                  '&:focus': {
                    borderColor: 'rgb(0, 36, 61)',
                    outline: '2px solid rgb(0, 36, 61)',
                    outlineOffset: '2px',
                  },
                },
              }}
            />

            <TextInput
              leftSection={<IconUser size={16} />}
              label="Cvent Registration Number"
              placeholder="Enter registration number here"
              value={personRegistration}
              onChange={(event) => setpersonRegistration(event.currentTarget.value)}
              required
              styles={{
                input: {
                  backgroundColor: 'white',
                  border: '1px solid rgb(206, 212, 218)',
                  '&:focus': {
                    borderColor: 'rgb(0, 36, 61)',
                    outline: '2px solid rgb(0, 36, 61)',
                    outlineOffset: '2px',
                  },
                },
              }}
            />


            {/* Photo Section */}
            <Box>
              <Text size="sm" fw={700} mb="xs">
                Upload photo with clear Face
              </Text>

              <Group grow>
                <FileInput
                  leftSection={<IconUpload size={16} />}
                  placeholder="Upload photo"
                  accept="image/*"
                  value={photoFile}
                  onChange={setPhotoFile}
                  styles={{
                    input: {
                      backgroundColor: 'white',
                      border: '1px solid rgb(206, 212, 218)',
                      '&:focus': {
                        borderColor: 'rgb(0, 36, 61)',
                        outline: '2px solid rgb(0, 36, 61)',
                        outlineOffset: '2px',
                      },
                    },
                  }}
                />

                <Button
                  leftSection={<IconCamera size={16} />}
                  onClick={handleStartCapture}
                  loading={isCapturing}
                  variant="light"
                  color="signature"
                  disabled={cameraSettings && cameraSettings.source === 'rtsp'}
                  styles={{
                    root: {
                      backgroundColor: 'rgba(0, 36, 61, 0.1)',
                      color: 'rgb(0, 36, 61)',
                      border: '1px solid rgb(0, 36, 61)',
                      '&:hover': {
                        backgroundColor: 'rgba(0, 36, 61, 0.2)',
                      },
                      '&:disabled': {
                        backgroundColor: 'rgba(128, 128, 128, 0.1)',
                        color: 'rgba(128, 128, 128, 0.6)',
                        border: '1px solid rgba(128, 128, 128, 0.3)',
                      },
                    },
                  }}
                >
                  {isCapturing ? 'Capturing...' : 'Capture'}
                </Button>
              </Group>

              {/* RTSP Camera Information */}
              {cameraSettings && cameraSettings.source === 'rtsp' && (
                <Alert
                  color="blue"
                  title="RTSP Camera Configured"
                  style={{ marginTop: '0.5rem' }}
                >
                  Camera capture is disabled because an RTSP camera is configured. Please use the file upload option instead.
                </Alert>
              )}

              {/* Photo Preview */}
              {(capturedPhoto || photoFile) && (
                <Box mt="md" ta="center">
                  <Text size="sm" c="rgb(0, 36, 61)" mb="xs">
                    Photo Preview:
                  </Text>
                  {capturedPhoto && (
                    <Box
                      style={{
                        width: 150,
                        height: 150,
                        border: '2px solid rgb(0, 36, 61)',
                        borderRadius: '8px',
                        margin: '0 auto',
                        overflow: 'hidden',
                      }}
                    >
                      <Image
                        src={capturedPhoto}
                        alt="Captured photo"
                        fit="cover"
                        h={146}
                        w={146}
                      />
                    </Box>
                  )}
                  {photoFile && photoFileUrl && (
                    <Box
                      style={{
                        width: 150,
                        height: 150,
                        border: '2px solid rgb(0, 36, 61)',
                        borderRadius: '8px',
                        margin: '0 auto',
                        overflow: 'hidden',
                      }}
                    >
                      <Image
                        src={photoFileUrl}
                        alt="Uploaded photo"
                        fit="cover"
                        h={146}
                      />
                    </Box>
                  )}
                </Box>
              )}
            </Box>

            {/* Error Alert */}
            {error && (
              <Alert
                icon={<IconAlertCircle size={16} />}
                color="red"
                title="Error"
              >
                {error}
              </Alert>
            )}

            {/* Success Alert */}
            {success && (
              <Alert
                color="green"
                title="Success"
              >
                {success}
              </Alert>
            )}

            {/* Validation Alert */}
            {!error && !success && !csvFile && (!personName || !personTitle || !personRegistration || (!photoFile && !capturedPhoto)) && (
              <Alert
                icon={<IconAlertCircle size={16} />}
                color="orange"
                title="Required Fields"
              >
                Please fill in all fields and upload/capture a photo before registering.
              </Alert>
            )}

            {/* Register Button */}
            <Button
              leftSection={<IconUserPlus size={16} />}
              onClick={handleRegister}
              loading={loading}
              fullWidth
              color="signature"
              style={{ marginTop: '1rem' }}
              disabled={!personName || !personTitle || !personRegistration || (!photoFile && !capturedPhoto) || loading || csvFile}
            >
              {loading ? 'Registering...' : 'Register'}
            </Button>
          </Stack>
        </Paper>

        {/* Additional Photos Section - Only show after successful registration */}
        {registeredPersonId && (
          <Paper
            ref={additionalPhotosRef}
            shadow="md"
            p="xl"
            radius="md"
            style={{
              backgroundColor: 'white',
              width: '100%',
            }}
          >
            <Stack gap="md">
              <Title order={3} ta="center" mb="md">
                Add Additional Photos (Optional)
              </Title>

              <Text size="sm" c="dimmed" ta="center" mb="md">
                Adding more photos helps improve recognition accuracy, especially with different lighting, angles, or accessories.
              </Text>

              {/* Photo Recommendations */}
              <Alert
                color="blue"
                title="Photo Suggestions"
                icon={<IconPhoto size={16} />}
              >
                <Text size="sm" mb="sm">Adding multiple photos helps improve recognition accuracy. Consider photos with:</Text>
                <List
                  spacing="xs"
                  size="sm"
                  center
                  icon={
                    <ThemeIcon color="blue" size={24} radius="xl">
                      <IconCheck size={12} />
                    </ThemeIcon>
                  }
                >
                  <List.Item icon={<ThemeIcon color="blue" size={16} radius="xl"><IconEye size={10} /></ThemeIcon>}>
                    Different facial expressions or angles
                  </List.Item>
                  <List.Item icon={<ThemeIcon color="blue" size={16} radius="xl"><IconSun size={10} /></ThemeIcon>}>
                    Various lighting conditions
                  </List.Item>
                  <List.Item icon={<ThemeIcon color="blue" size={16} radius="xl"><IconPhoto size={10} /></ThemeIcon>}>
                    With and without accessories (glasses, hats, etc.)
                  </List.Item>
                </List>
              </Alert>

              {/* Additional Photo Upload */}
              <Group grow>
                <FileInput
                  leftSection={<IconUpload size={16} />}
                  placeholder="Upload additional photo"
                  accept="image/*"
                  onChange={(file) => file && handleAddAdditionalPhoto(file)}
                  disabled={additionalPhotoLoading}
                  styles={{
                    input: {
                      backgroundColor: 'white',
                      border: '1px solid rgb(206, 212, 218)',
                      '&:focus': {
                        borderColor: 'rgb(0, 36, 61)',
                        outline: '2px solid rgb(0, 36, 61)',
                        outlineOffset: '2px',
                      },
                    },
                  }}
                />

                <Button
                  leftSection={<IconCamera size={16} />}
                  onClick={handleStartAdditionalCapture}
                  loading={additionalPhotoLoading}
                  variant="light"
                  color="signature"
                  disabled={(cameraSettings && cameraSettings.source === 'rtsp') || additionalPhotoLoading}
                  styles={{
                    root: {
                      backgroundColor: 'rgba(0, 36, 61, 0.1)',
                      color: 'rgb(0, 36, 61)',
                      border: '1px solid rgb(0, 36, 61)',
                      '&:hover': {
                        backgroundColor: 'rgba(0, 36, 61, 0.2)',
                      },
                      '&:disabled': {
                        backgroundColor: 'rgba(128, 128, 128, 0.1)',
                        color: 'rgba(128, 128, 128, 0.6)',
                        border: '1px solid rgba(128, 128, 128, 0.3)',
                      },
                    },
                  }}
                >
                  Capture
                </Button>
              </Group>

              {/* Additional Photo Error */}
              {additionalPhotoError && (
                <Alert
                  icon={<IconAlertCircle size={16} />}
                  color="red"
                  title="Error"
                >
                  {additionalPhotoError}
                </Alert>
              )}

              {/* Additional Photo Success */}
              {additionalPhotoSuccess && (
                <Alert
                  color="green"
                  title="Success"
                >
                  {additionalPhotoSuccess}
                </Alert>
              )}

              {/* Additional Photos Preview */}
              {additionalPhotos.length > 0 && (
                <Box>
                  <Text size="sm" fw={500} mb="xs">
                    Additional Photos ({additionalPhotos.length}):
                  </Text>
                  <Group gap="sm">
                    {additionalPhotos.map((photo, index) => (
                      <Box
                        key={index}
                        style={{
                          width: 80,
                          height: 80,
                          border: '1px solid rgb(206, 212, 218)',
                          borderRadius: '8px',
                          overflow: 'hidden',
                          position: 'relative',
                        }}
                      >
                        <Image
                          src={photo.url}
                          alt={`Additional photo ${index + 1}`}
                          fit="cover"
                          h={78}
                          w={78}
                        />
                        <Text
                          size="xs"
                          style={{
                            position: 'absolute',
                            bottom: 0,
                            left: 0,
                            right: 0,
                            backgroundColor: 'rgba(0, 0, 0, 0.7)',
                            color: 'white',
                            padding: '2px 4px',
                            fontSize: '10px',
                          }}
                        >
                          #{index + 1}
                        </Text>
                      </Box>
                    ))}
                  </Group>
                </Box>
              )}

              <Divider />

              {/* Action Buttons */}
              <Group justify="center" gap="md">
                <Button
                  variant="light"
                  color="signature"
                  onClick={handleStartOver}
                  disabled={additionalPhotoLoading}
                >
                  Register Another Person
                </Button>
                <Button
                  variant="outline"
                  color="signature"
                  onClick={() => {
                    // Just clear the registered person ID to hide this section
                    setRegisteredPersonId(null);
                    setAdditionalPhotos([]);
                    setAdditionalPhotoError('');
                    setAdditionalPhotoSuccess('');
                  }}
                  disabled={additionalPhotoLoading}
                >
                  Done Adding Photos
                </Button>
              </Group>
            </Stack>
          </Paper>
        )}
      </Stack>


      {/* Camera Capture Modal */}
      {opened && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 10000
        }}>
          <div style={{
            backgroundColor: 'white',
            padding: '30px',
            borderRadius: '8px',
            maxWidth: '500px',
            textAlign: 'center'
          }}>
            <h2 style={{ color: 'rgb(0, 36, 61)', marginBottom: '10px' }}>Capture person Photo</h2>
            <p style={{ color: 'rgb(0, 36, 61)', marginBottom: '20px', fontSize: '14px' }}>
              Position your face inside the green rectangle
            </p>
            <div style={{
              position: 'relative',
              display: 'inline-block',
              marginBottom: '20px'
            }}>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                style={{
                  width: '400px',
                  height: '300px',
                  border: '2px solid rgb(0, 36, 61)',
                  borderRadius: '8px',
                  objectFit: 'cover'
                }}
              />
              {/* Face placement guide - green rectangle overlay */}
              <div
                style={{
                  position: 'absolute',
                  top: '2px', // Account for border
                  left: '2px', // Account for border
                  width: 'calc(100% - 4px)', // Account for both borders
                  height: 'calc(100% - 4px)', // Account for both borders
                  pointerEvents: 'none',
                  borderRadius: '6px', // Slightly less than video to fit inside
                  overflow: 'hidden'
                }}
              >
                {/* Semi-transparent overlay with cutout for face */}
                <div style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  background: `
                    radial-gradient(
                      ellipse 140px 180px at center,
                      transparent 50%,
                      rgba(0, 0, 0, 0.4) 60%
                    )
                  `
                }} />

                {/* Green face guide rectangle */}
                <div
                  style={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    width: '140px',
                    height: '180px',
                    border: '3px solid #00AA7F',
                    borderRadius: '12px',
                    transform: 'translate(-50%, -50%)',
                    boxShadow: '0 0 10px rgba(0, 170, 127, 0.5)'
                  }}
                >
                  {/* Corner guides */}
                  <div style={{
                    position: 'absolute',
                    top: '-3px',
                    left: '-3px',
                    width: '15px',
                    height: '15px',
                    border: '3px solid #00AA7F',
                    borderRight: 'none',
                    borderBottom: 'none',
                    borderRadius: '3px 0 0 0'
                  }} />
                  <div style={{
                    position: 'absolute',
                    top: '-3px',
                    right: '-3px',
                    width: '15px',
                    height: '15px',
                    border: '3px solid #00AA7F',
                    borderLeft: 'none',
                    borderBottom: 'none',
                    borderRadius: '0 3px 0 0'
                  }} />
                  <div style={{
                    position: 'absolute',
                    bottom: '-3px',
                    left: '-3px',
                    width: '15px',
                    height: '15px',
                    border: '3px solid #00AA7F',
                    borderRight: 'none',
                    borderTop: 'none',
                    borderRadius: '0 0 0 3px'
                  }} />
                  <div style={{
                    position: 'absolute',
                    bottom: '-3px',
                    right: '-3px',
                    width: '15px',
                    height: '15px',
                    border: '3px solid #00AA7F',
                    borderLeft: 'none',
                    borderTop: 'none',
                    borderRadius: '0 0 3px 0'
                  }} />
                </div>

                {/* Instructions text overlay */}
                <div style={{
                  position: 'absolute',
                  top: '10px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  color: '#00AA7F',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  textShadow: '2px 2px 4px rgba(0, 0, 0, 0.8)',
                  textAlign: 'center',
                  background: 'rgba(0, 0, 0, 0.5)',
                  padding: '4px 8px',
                  borderRadius: '4px'
                }}>
                  Position face in green area
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
              <Button
                onClick={handleCapturePhoto}
                color="signature"
                style={{
                  padding: '10px 20px',
                  borderRadius: '4px',
                }}
              >
                📷 Take Photo
              </Button>
              <Button
                onClick={handleStopCapture}
                color="signature"
                variant="outline"
                style={{
                  padding: '10px 20px',
                  borderRadius: '4px',
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Additional Photo Camera Capture Modal */}
      {additionalCaptureOpened && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 10000
        }}>
          <div style={{
            backgroundColor: 'white',
            padding: '30px',
            borderRadius: '8px',
            maxWidth: '500px',
            textAlign: 'center'
          }}>
            <h2 style={{ color: 'rgb(0, 36, 61)', marginBottom: '10px' }}>Capture Additional Photo</h2>
            <p style={{ color: 'rgb(0, 36, 61)', marginBottom: '20px', fontSize: '14px' }}>
              Position your face inside the green rectangle
            </p>
            <div style={{
              position: 'relative',
              display: 'inline-block',
              marginBottom: '20px'
            }}>
              <video
                ref={additionalVideoRef}
                autoPlay
                playsInline
                style={{
                  width: '400px',
                  height: '300px',
                  border: '2px solid rgb(0, 36, 61)',
                  borderRadius: '8px',
                  objectFit: 'cover'
                }}
              />
              {/* Face placement guide - green rectangle overlay */}
              <div
                style={{
                  position: 'absolute',
                  top: '2px',
                  left: '2px',
                  width: 'calc(100% - 4px)',
                  height: 'calc(100% - 4px)',
                  pointerEvents: 'none',
                  borderRadius: '6px',
                  overflow: 'hidden'
                }}
              >
                {/* Semi-transparent overlay with cutout for face */}
                <div style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  background: `
                    radial-gradient(
                      ellipse 140px 180px at center,
                      transparent 50%,
                      rgba(0, 0, 0, 0.4) 60%
                    )
                  `
                }} />

                {/* Green face guide rectangle */}
                <div
                  style={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    width: '140px',
                    height: '180px',
                    border: '3px solid #00AA7F',
                    borderRadius: '12px',
                    transform: 'translate(-50%, -50%)',
                    boxShadow: '0 0 10px rgba(0, 170, 127, 0.5)'
                  }}
                />

                {/* Instructions text overlay */}
                <div style={{
                  position: 'absolute',
                  top: '10px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  color: '#00AA7F',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  textShadow: '2px 2px 4px rgba(0, 0, 0, 0.8)',
                  textAlign: 'center',
                  background: 'rgba(0, 0, 0, 0.5)',
                  padding: '4px 8px',
                  borderRadius: '4px'
                }}>
                  Position face in green area
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
              <Button
                onClick={handleCaptureAdditionalPhoto}
                color="signature"
                loading={additionalPhotoLoading}
                style={{
                  padding: '10px 20px',
                  borderRadius: '4px',
                }}
              >
                📷 Take Photo
              </Button>
              <Button
                onClick={handleStopAdditionalCapture}
                color="signature"
                variant="outline"
                style={{
                  padding: '10px 20px',
                  borderRadius: '4px',
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

    </Box>
  );
}