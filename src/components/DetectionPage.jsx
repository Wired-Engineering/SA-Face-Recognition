import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Paper,
  Stack,
  Title,
  Button,
  Group,
  Box,
  Text,
  Card,
  Badge,
  Alert,
  Grid,
  useMantineTheme,
  LoadingOverlay,
} from '@mantine/core';
import {
  IconVideo,
  IconVideoOff,
  IconAlertCircle,
  IconHome,
} from '@tabler/icons-react';
import apiService from '../services/api';
import { useSocket } from '../hooks/useSocket';
import { openWelcomePopup } from '../services/welcomePopup';

export function DetectionPage({ onDetection }) {
  const theme = useMantineTheme();
  const { isConnected, connectionState, connect, disconnect, on, emit } = useSocket();
  const [isVideoStarted, setIsVideoStarted] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [detectedPerson, setDetectedPerson] = useState(null);
  const [detectionHistory, setDetectionHistory] = useState([]);
  const [videoStatus, setVideoStatus] = useState('Stopped');
  const [error, setError] = useState(null);
  const [actualCameraSource, setActualCameraSource] = useState('default');
  const rtspImageRef = useRef(null);
  const frameProcessingIntervalRef = useRef(null);
  const isDetectingRef = useRef(false);
  const [isStreamLoading, setIsStreamLoading] = useState(false);

  // Handle detection results for UI updates
  const handleDetectionResult = useCallback((data) => {
    // console.log('🔍 Received detection results:', data);

    // Update UI state for both RTSP and webcam modes
    if (data.faces && data.faces.length > 0) {
      // Find the best recognition result
      const recognizedFaces = data.faces.filter(face => face.recognized);
      const bestMatch = recognizedFaces.length > 0 ?
        recognizedFaces.reduce((best, current) =>
          current.match_confidence > best.match_confidence ? current : best
        ) : null;

      if (bestMatch) {
        const detectedPerson = {
          id: bestMatch.person_id,
          name: bestMatch.person_name,
          title: bestMatch.person_title,
          confidence: Math.round(bestMatch.match_confidence * 100),
          bbox: bestMatch.bbox
        };

        setDetectedPerson(detectedPerson);

        // Note: Welcome popup is now only opened manually via header button
        // Recognition data will still be sent to any open welcome screens via SocketIO

        // Only add to history if it's a new person or significant time has passed
        const now = new Date().toLocaleString();
        setDetectionHistory(prev => {
          const lastDetection = prev[0];
          if (!lastDetection ||
              lastDetection.id !== detectedPerson.id ||
              Date.now() - new Date(lastDetection.rawTimestamp || 0).getTime() > 5000) {
            return [{
              ...detectedPerson,
              timestamp: now,
              rawTimestamp: Date.now()
            }, ...prev.slice(0, 9)]; // Keep last 10
          }
          return prev;
        });

        onDetection?.(detectedPerson);
      } else {
        // Unknown person detected
        setDetectedPerson({
          id: 'UNKNOWN',
          name: 'Unknown Person',
          confidence: 0,
          bbox: data.faces[0].bbox
        });
      }
    } else {
      setDetectedPerson(null);
    }
  }, [onDetection]);

  // Setup SocketIO connection using the socket provider
  const setupSocketIOConnection = useCallback(async () => {
    console.log('🔌 Setting up SocketIO connection...');

    try {
      // Check if socket is already connected
      if (isConnected) {
        console.log('🔌 Socket already connected, reusing existing connection');

        // Start detection immediately
        console.log('🎯 Emitting start_detection...');
        emit('start_detection', {});

        setIsDetecting(true);
        isDetectingRef.current = true;
        return;
      }

      // Connect using the socket provider - this now returns a Promise
      console.log('🔌 Initiating connection via provider...');
      const socket = await connect();

      if (!socket) {
        throw new Error('Failed to establish socket connection');
      }

      console.log('🔌 Socket connection established');

      // Start detection after successful connection
      console.log('🎯 Emitting start_detection...');
      emit('start_detection', {});

      console.log('🎯 Setting isDetecting to true...');
      setIsDetecting(true);
      isDetectingRef.current = true;

      console.log('🔌 SocketIO setup complete');
    } catch (error) {
      console.error('🔌 Failed to setup SocketIO:', error);
      setError(`Connection setup failed: ${error.message}`);
    }
  }, [isConnected, connect, emit]);

  const handleStopDetection = useCallback((adminStop = false) => {
    setIsDetecting(false);
    isDetectingRef.current = false;
    setDetectedPerson(null);

    // Stop frame processing
    if (frameProcessingIntervalRef.current) {
      clearInterval(frameProcessingIntervalRef.current);
      frameProcessingIntervalRef.current = null;
    }

    // Tell backend to stop detection
    if (isConnected) {
      emit('stop_detection', { admin_stop: adminStop });
    }
  }, [isConnected, emit]);

  const handleStartVideo = useCallback(async () => {
    try {
      setError(null);
      setVideoStatus('Connecting...');
      console.log('🎥 Starting video...');

      // Load saved camera settings
      const cameraSettings = await apiService.getCameraSettings();
      console.log('📷 Loaded camera settings:', cameraSettings);
      console.log('📷 cameraSettings.source value:', cameraSettings.source);
      console.log('📷 cameraSettings.source type:', typeof cameraSettings.source);


      // Apply saved camera settings
      if (cameraSettings.success || cameraSettings.source) {
        if (cameraSettings.source === 'rtsp') {
          // RTSP camera - use HTTP video stream with overlays from backend
          console.log('📡 RTSP camera selected, using ffmpeg stream with overlays');

          // Set RTSP mode
          setActualCameraSource('rtsp');

          // Set video source to ffmpeg stream with overlays endpoint
          setIsVideoStarted(true);
          setVideoStatus('Connecting to RTSP...');
          setIsStreamLoading(true); // Start loading state

          // Set up RTSP image stream with overlays after state update
          setTimeout(() => {
            if (rtspImageRef.current) {
              rtspImageRef.current.src = '/api/rtsp/stream-with-overlay';
              console.log('📡 RTSP stream source set to /api/rtsp/stream-with-overlay');
            }
          }, 100);

          // Use Socket.IO connection for welcome screen recognition events only
          await setupSocketIOConnection();
          return; // Skip getUserMedia for RTSP
        } else if (cameraSettings.source === 'webcam' || cameraSettings.source === 'device' || cameraSettings.source === 'default') {
          // Webcam/Device/Default - use HTTP video stream with overlays from backend (just like RTSP)
          console.log('📹 Webcam/Device/Default selected, using backend stream with overlays');
          console.log('📹 Setting actualCameraSource to:', cameraSettings.source);
          if (cameraSettings.device_id) {
            console.log('📹 Using webcam device:', cameraSettings.device_id);
          }

          // Set webcam streaming mode
          setActualCameraSource(cameraSettings.source);
          setIsVideoStarted(true);
          setVideoStatus('Connecting to webcam...');
          setIsStreamLoading(true); // Start loading state

          // Set up webcam stream with overlays after state update
          setTimeout(() => {
            if (rtspImageRef.current) {
              rtspImageRef.current.src = '/api/webcam/stream-with-overlay';
              console.log('📹 Webcam stream source set to /api/webcam/stream-with-overlay');

              // Set status once stream loads
              rtspImageRef.current.onload = () => {
                setVideoStatus('Webcam Active');
                setIsStreamLoading(false); // Stop loading when loaded
              };
              rtspImageRef.current.onerror = () => {
                setVideoStatus('Webcam Error');
                setError('Failed to connect to webcam stream');
                setIsStreamLoading(false); // Stop loading on error
              };
            }
          }, 100);

          // Use Socket.IO for welcome screen events
          await setupSocketIOConnection();
          return; // Skip getUserMedia for webcam streaming
        }
        // If source is not rtsp, webcam, device, or default, fall through to legacy getUserMedia
      }

      // This should not happen with current streaming architecture
      console.error('🚨 Unexpected fallthrough to legacy getUserMedia path');
      throw new Error('Unsupported camera configuration');

    } catch (err) {
      console.error('❌ Error starting video:', err);
      setError(`Failed to start camera: ${err.message}`);
      setVideoStatus('Error');
      setIsVideoStarted(false);
    }
  }, [setupSocketIOConnection]);

  const handleStopVideo = useCallback(async () => {
    // console.log('🛑 handleStopVideo called');
    // console.trace('🛑 Stop video called from:');

    // Stop detection if active (admin explicit stop)
    if (isDetectingRef.current) {
      handleStopDetection(true);
    }

    // Stop backend streams for both device and RTSP sources
    console.log('🔍 Debug stop - actualCameraSource:', actualCameraSource);
    try {
      if (actualCameraSource === 'rtsp') {
        console.log('🛑 Stopping RTSP streams...');
        await apiService.stopRtspStreams();
        console.log('✅ RTSP streams stopped');
      } else if (actualCameraSource === 'device' || actualCameraSource === 'webcam' || actualCameraSource === 'default') {
        console.log('🛑 Stopping device streams...');
        await apiService.stopWebcamStreams();
        console.log('✅ Device streams stopped');
      }
    } catch (error) {
      console.error('❌ Error stopping streams:', error);
    }

    // Close SocketIO connection
    console.log('🔌 Closing SocketIO connection...');
    disconnect();

    // Stop frame processing
    if (frameProcessingIntervalRef.current) {
      console.log('🖼️ Stopping frame processing...');
      clearInterval(frameProcessingIntervalRef.current);
      frameProcessingIntervalRef.current = null;
    }

    // Clear the stream image source to prevent stale frames
    if (rtspImageRef.current) {
      rtspImageRef.current.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'; // 1x1 transparent GIF
    }

    setIsVideoStarted(false);
    setIsDetecting(false);
    setVideoStatus('Stopped');
    setDetectedPerson(null);
    setError(null);
    setIsStreamLoading(false);
  }, [actualCameraSource, disconnect, handleStopDetection]);


  // Check for persistent detection state on mount
  useEffect(() => {
    const checkAutoStart = async () => {
      try {
        const status = await apiService.getDetectionStatus();
        if (status.should_auto_start && !isVideoStarted) {
          console.log('🔄 Auto-starting detection from persistent state');
          await handleStartVideo();
        }
      } catch (error) {
        console.error('❌ Error checking auto-start status:', error);
      }
    };

    checkAutoStart();
  }, [handleStartVideo, isVideoStarted]); // Include dependencies

  // Setup socket event listeners
  useEffect(() => {
    if (!isConnected) return;

    // Handle face detection results from SocketIO (for welcome screen events)
    const cleanupDetectionResult = on('face_detection_result', (data) => {
      handleDetectionResult(data);
    });

    const cleanupDetectionStarted = on('detection_started', (data) => {
      console.log('🎯 Detection started:', data);
    });

    const cleanupDetectionStopped = on('detection_stopped', (data) => {
      console.log('🛑 Detection stopped:', data);
    });

    const cleanupDetectionError = on('detection_error', (error) => {
      console.error('❌ Detection error:', error);
      setError(`Detection error: ${error.error}`);
    });

    const cleanupError = on('error', (error) => {
      console.error('🔌 SocketIO error:', error);
    });

    // Cleanup function
    return () => {
      cleanupDetectionResult?.();
      cleanupDetectionStarted?.();
      cleanupDetectionStopped?.();
      cleanupDetectionError?.();
      cleanupError?.();
    };
  }, [isConnected, on, handleDetectionResult]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      console.log('🧹 Component cleanup triggered - preserving detection state');
      // Only disconnect socket, do NOT send stop_detection to preserve detection for welcome screens
      setIsVideoStarted(false);
      setIsDetecting(false);
    };
  }, []); // Empty dependency array - only run on mount/unmount

  // Note: Removed automatic stream cleanup on page unload to preserve detection state
  // Detection should persist across admin page refreshes for welcome screens
  // Only explicit admin "Stop Video" should stop detection

  return (
    <Box style={{ width: '100%', minHeight: '100%' }}>
      <Box style={{ padding: '24px' }}>
        <Title order={2} ta="center" c="white" mb="xl">
          Live Face Detection
        </Title>

      {error && (
        <Alert color="red" title="Error" icon={<IconAlertCircle size={16} />} mb="md">
          {error}
        </Alert>
      )}


      <Grid gutter="md" style={{ margin: 0 }}>
        {/* Video Feed Section */}
        <Grid.Col span={9}>
          <Card shadow="md" radius="md" withBorder>
            <Stack gap="md">
              <Group justify="space-between">
                <Title order={4}>
                  Camera Feed
                </Title>
                <Badge
                  color={isConnected ? 'green' : connectionState === 'connecting' ? 'yellow' : 'red'}
                  variant="filled"
                  size="lg"
                >
                  {isConnected ? 'SocketIO Connected' :
                   connectionState === 'connecting' ? 'Connecting...' :
                   connectionState === 'disconnected' ? 'Disconnected' :
                   videoStatus}
                </Badge>
              </Group>

              {/* Video Feed Display */}
              <Box
                style={{
                  width: '100%',
                  aspectRatio: '16/9',
                  backgroundColor: isVideoStarted ? '#000' : '#f8fafc',
                  border: '2px solid #ddd',
                  borderRadius: '8px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  position: 'relative',
                }}
              >
                {!isVideoStarted ? (
                  <Group>
                    <IconVideoOff size={48} color="gray" />
                    <Text size="lg">
                      Camera Feed Stopped
                    </Text>
                  </Group>
                ) : (
                  <Box style={{ position: 'relative', width: '100%', height: '100%' }}>
                    <LoadingOverlay visible={isStreamLoading} loaderProps={{ size: 'lg' }} />
                    {/* MJPEG stream with backend overlays for both device and RTSP sources */}
                    <img
                      ref={rtspImageRef}
                      alt="Camera Stream"
                      style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                        borderRadius: '6px',
                        display: 'block'
                      }}
                      onLoad={() => {
                        console.log('📡 Camera stream loaded successfully');
                        setVideoStatus('Connected');
                        setError(null);
                        setIsStreamLoading(false); // Stop loading when stream loads
                      }}
                      onError={(e) => {
                        console.error('📡 Camera stream error:', e);
                        setError('Camera stream failed to load. Check camera connection.');
                        setVideoStatus('Connection Failed');
                        setIsStreamLoading(false); // Stop loading on error
                      }}
                    />

                    {/* Detection Overlay */}
                    {isDetecting && detectedPerson && (
                      <Box
                        style={{
                          position: 'absolute',
                          top: 20,
                          left: 20,
                          backgroundColor: 'white',
                          color: 'white',
                          padding: '10px',
                          borderRadius: '8px',
                          border: `2px solid ${
                            detectedPerson.confidence > 80 ? 'green' : 'orange'
                          }`,
                        }}
                      >
                        <Text size="sm" fw={700}>
                          {detectedPerson.name}
                        </Text>
                        {detectedPerson.title && (
                          <Text size="xs">
                            {detectedPerson.title}
                          </Text>
                        )}
                        <Text size="xs">
                          Confidence: {detectedPerson.confidence}%
                        </Text>
                        <Text size="xs">
                          ID: {detectedPerson.id}
                        </Text>
                      </Box>
                    )}
                  </Box>
                )}
              </Box>

              {/* Control Buttons */}
              <Group justify="center" gap="md">
                <Button
                  leftSection={<IconVideo size={20} />}
                  onClick={handleStartVideo}
                  disabled={Boolean(isVideoStarted || isStreamLoading)}
                  loading={isStreamLoading && !isVideoStarted}
                  color="signature"
                  style={{
                    opacity: (isVideoStarted || isStreamLoading) ? 0.6 : 1,
                    pointerEvents: (isVideoStarted || isStreamLoading) ? 'none' : 'auto'
                  }}
                >
                  Start Camera & Detection
                </Button>

                <Button
                  leftSection={<IconVideoOff size={20} />}
                  onClick={handleStopVideo}
                  disabled={!isVideoStarted || isStreamLoading}
                  color="red"
                  variant="filled"
                >
                  Stop Camera
                </Button>

                <Button
                  leftSection={<IconHome size={20} />}
                  onClick={() => {
                    // Get display settings from localStorage
                    const savedSettings = localStorage.getItem('faceRecognitionDisplaySettings');
                    let displaySettings = {
                      backgroundColor: theme.other.cardBackground,
                      fontColor: theme.other.textDark,
                      timer: 5
                    };

                    if (savedSettings) {
                      try {
                        displaySettings = { ...displaySettings, ...JSON.parse(savedSettings) };
                      } catch (e) {
                        console.warn('Failed to parse display settings:', e);
                      }
                    }

                    console.log('🪟 Opening welcome canvas from detection page');
                    openWelcomePopup(displaySettings);
                  }}
                  color="green"
                  variant="filled"
                >
                  Welcome Canvas
                </Button>
              </Group>

            </Stack>
          </Card>
        </Grid.Col>

        {/* Detection Info Section */}
        <Grid.Col span={3}>
          <Stack gap="md">
            {/* Current Detection */}
            <Card shadow="md" radius="md" withBorder>
              <Title order={5} mb="md">
                Current Detection
              </Title>

              {detectedPerson ? (
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={600}>Name:</Text>
                    <Text>{detectedPerson.name}</Text>
                  </Group>
                  <Group justify="space-between">
                    <Text fw={600}>ID:</Text>
                    <Text>{detectedPerson.id}</Text>
                  </Group>
                  {detectedPerson.title && (
                    <Group justify="space-between">
                      <Text fw={600}>Title:</Text>
                      <Text>{detectedPerson.title}</Text>
                    </Group>
                  )}
                  <Group justify="space-between">
                    <Text fw={600}>Confidence:</Text>
                    <Badge
                      color={detectedPerson.confidence > 80 ? 'green' : 'orange'}
                    >
                      {detectedPerson.confidence}%
                    </Badge>
                  </Group>
                </Stack>
              ) : (
                <Text ta="center" py="md">
                  {isDetecting ? 'Scanning for faces...' : 'No detection active'}
                </Text>
              )}
            </Card>

            {/* Detection History */}
            <Card shadow="md" radius="md" withBorder>
              <Title order={5} mb="md">
                Recent Detections
              </Title>

              <Stack gap="xs" style={{ maxHeight: 300, overflowY: 'auto' }}>
                {detectionHistory.length === 0 ? (
                  <Text ta="center" py="md">
                    No recent detections
                  </Text>
                ) : (
                  detectionHistory.map((detection, index) => (
                    <Paper key={index} p="xs" withBorder>
                      <Group justify="space-between" gap="xs">
                        <Box style={{ flex: 1 }}>
                          <Text size="sm" fw={600}>
                            {detection.name}
                          </Text>
                          {detection.title && (
                            <Text size="xs" style={{ opacity: 0.8 }}>
                              {detection.title}
                            </Text>
                          )}
                          <Text size="xs">
                            {detection.timestamp}
                          </Text>
                        </Box>
                        <Badge
                          size="sm"
                          color={detection.confidence > 80 ? 'green' : 'orange'}
                        >
                          {detection.confidence}%
                        </Badge>
                      </Group>
                    </Paper>
                  ))
                )}
              </Stack>
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>
      </Box>
    </Box>
  );
}