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
  Modal,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconUser, IconId, IconCamera, IconUpload, IconUserPlus, IconAlertCircle } from '@tabler/icons-react';
import apiService, { imageUtils, webcamUtils } from '../services/api';

export function RegistrationPage({ onRegister }) {
  const [studentId, setStudentId] = useState('');
  const [studentName, setStudentName] = useState('');
  const [photoFile, setPhotoFile] = useState(null);
  const [capturedPhoto, setCapturedPhoto] = useState(null);
  const [isCapturing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [stream, setStream] = useState(null);
  const [opened, { open, close }] = useDisclosure(false);

  const videoRef = useRef(null);


  const handleStartCapture = async () => {
    try {
      open();
      const mediaStream = await webcamUtils.getUserMedia();
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
      handleStopCapture();
    }
  };

  const handleStopCapture = () => {
    if (stream) {
      webcamUtils.stopStream(stream);
      setStream(null);
    }
    close();
  };

  const handleRegister = async () => {
    if (!studentId || !studentName || (!photoFile && !capturedPhoto)) {
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

      const result = await apiService.registerStudent(studentId, studentName, imageData);

      if (result.success) {
        setSuccess(`Student ${studentName} registered successfully!`);
        // Reset form
        setStudentId('');
        setStudentName('');
        setPhotoFile(null);
        setCapturedPhoto(null);

        // Call parent callback if provided
        onRegister?.({
          id: studentId,
          name: studentName,
          photo: imageData,
        });
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

  return (
    <Box style={{ width: '100%', minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Stack gap="xl" style={{ maxWidth: '600px' }}>
        {/* Header */}
        <Box ta="center" mb="md">
          <Title order={2} c="rgb(0, 36, 61)" mb="xs">
            Student Registration
          </Title>
        </Box>

        {/* Registration Form */}
        <Paper
          shadow="md"
          p="xl"
          radius="md"
          style={{
            backgroundColor: 'white',
            border: '1px solid rgb(0, 36, 61)',
          }}
        >
          <Stack gap="md">
            <Title order={3} ta="center" c="rgb(0, 36, 61)" mb="md">
              Register New Student
            </Title>

            {/* Student Information */}
            <TextInput
              leftSection={<IconId size={16} />}
              label="Student ID"
              placeholder="Enter ID here"
              value={studentId}
              onChange={(event) => setStudentId(event.currentTarget.value)}
              styles={{
                input: {
                  borderColor: 'rgb(0, 36, 61)',
                  minHeight: '30px',
                  '&:focus': {
                    borderColor: 'rgb(0, 170, 127)',
                  },
                },
              }}
              required
            />

            <TextInput
              leftSection={<IconUser size={16} />}
              label="Name"
              placeholder="Enter name here"
              value={studentName}
              onChange={(event) => setStudentName(event.currentTarget.value)}
              styles={{
                input: {
                  borderColor: 'rgb(0, 36, 61)',
                  minHeight: '30px',
                  '&:focus': {
                    borderColor: 'rgb(0, 170, 127)',
                  },
                },
              }}
              required
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
                      borderColor: 'rgb(0, 36, 61)',
                      '&:focus': {
                        borderColor: 'rgb(0, 170, 127)',
                      },
                    },
                  }}
                />

                <Button
                  leftSection={<IconCamera size={16} />}
                  onClick={handleStartCapture}
                  loading={isCapturing}
                  variant="outline"
                  style={{
                    borderColor: 'rgb(0, 36, 61)',
                    color: 'rgb(0, 36, 61)',
                    fontFamily: 'Tahoma',
                    fontWeight: 'bold',
                    fontSize: '10pt',
                    '&:hover': {
                      backgroundColor: 'rgb(0, 170, 127)',
                      color: 'white',
                      borderColor: 'rgb(0, 170, 127)',
                    },
                  }}
                >
                  {isCapturing ? 'Capturing...' : 'Capture'}
                </Button>
              </Group>

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
                  {photoFile && (
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
                        src={URL.createObjectURL(photoFile)}
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
            {!error && !success && (!studentId || !studentName || (!photoFile && !capturedPhoto)) && (
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
              style={{
                backgroundColor: 'rgb(0, 36, 61)',
                fontFamily: 'Tahoma',
                fontWeight: 'bold',
                fontSize: '10pt',
                marginTop: '1rem',
                '&:hover': {
                  backgroundColor: 'rgb(0, 170, 127)',
                },
              }}
              disabled={!studentId || !studentName || (!photoFile && !capturedPhoto) || loading}
            >
              {loading ? 'Registering...' : 'Register'}
            </Button>
          </Stack>
        </Paper>
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
            border: '1px solid rgb(0, 36, 61)',
            maxWidth: '500px',
            textAlign: 'center'
          }}>
            <h2 style={{ color: 'rgb(0, 36, 61)', marginBottom: '10px' }}>Capture Student Photo</h2>
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
                style={{
                  backgroundColor: 'rgb(0, 36, 61)',
                  color: 'white',
                  border: 'none',
                  padding: '10px 20px',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                📷 Take Photo
              </Button>
              <Button
                onClick={handleStopCapture}
                style={{
                  backgroundColor: 'transparent',
                  color: 'rgb(0, 36, 61)',
                  border: '2px solid rgb(0, 36, 61)',
                  padding: '10px 20px',
                  borderRadius: '4px',
                  cursor: 'pointer'
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