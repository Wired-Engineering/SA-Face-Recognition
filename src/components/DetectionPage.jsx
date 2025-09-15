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
} from '@mantine/core';
import {
  IconVideo,
  IconVideoOff,
  IconAlertCircle,
} from '@tabler/icons-react';
import { webcamUtils } from '../services/api';
import { io } from 'socket.io-client';

export function DetectionPage({ onDetection }) {
  const [isVideoStarted, setIsVideoStarted] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [detectedPerson, setDetectedPerson] = useState(null);
  const [detectionHistory, setDetectionHistory] = useState([]);
  const [videoStatus, setVideoStatus] = useState('Stopped');
  const [error, setError] = useState(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const socketRef = useRef(null);
  const frameProcessingIntervalRef = useRef(null);
  const isDetectingRef = useRef(false);
  const [connectionState, setConnectionState] = useState('disconnected');


  const handleStartVideo = async () => {
    try {
      setError(null);
      setVideoStatus('Connecting...');
      console.log('🎥 Starting video with default camera');

      // Get user media with default camera
      const constraints = {
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30 }
        },
        audio: false
      };

      console.log('📹 Requesting camera with constraints:', constraints);
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      console.log('✅ Camera stream acquired:', {
        active: stream.active,
        id: stream.id,
        tracks: stream.getVideoTracks().length
      });

      // Validate stream
      const videoTracks = stream.getVideoTracks();
      if (videoTracks.length === 0) {
        throw new Error('No video tracks in stream');
      }

      const videoTrack = videoTracks[0];
      console.log('📺 Video track:', {
        enabled: videoTrack.enabled,
        readyState: videoTrack.readyState,
        settings: videoTrack.getSettings()
      });

      streamRef.current = stream;

      // First, update state to render the video element
      setIsVideoStarted(true);
      setVideoStatus('Connected');
      console.log('✅ Video setup complete, rendering video element...');

      // Set up video element after state update (when component re-renders)
      setTimeout(async () => {
        if (videoRef.current && streamRef.current) {
          console.log('📺 Setting up video after render...');

          // Add event listeners for debugging
          videoRef.current.onloadstart = () => console.log('📺 Video loadstart');
          videoRef.current.onloadedmetadata = () => console.log('📺 Video metadata loaded');
          videoRef.current.oncanplay = () => console.log('📺 Video can play');
          videoRef.current.onplay = () => console.log('📺 Video started playing');
          videoRef.current.onplaying = () => console.log('📺 Video is playing');
          videoRef.current.onerror = (e) => console.error('📺 Video error:', e);

          // Set the stream
          videoRef.current.srcObject = streamRef.current;

          console.log('📺 Stream attached to video element:', {
            streamId: streamRef.current.id,
            streamActive: streamRef.current.active,
            videoElementExists: !!videoRef.current
          });

          try {
            await videoRef.current.play();
            console.log('📺 Video started playing successfully!');
          } catch (e) {
            console.log('📺 Video play failed:', e.message);
          }

          // Final status check
          setTimeout(() => {
            if (videoRef.current) {
              console.log('📺 Final video status check:', {
                readyState: videoRef.current.readyState,
                paused: videoRef.current.paused,
                videoWidth: videoRef.current.videoWidth,
                videoHeight: videoRef.current.videoHeight,
                currentTime: videoRef.current.currentTime,
                srcObject: !!videoRef.current.srcObject,
                srcObjectId: videoRef.current.srcObject?.id,
                stream: !!streamRef.current,
                streamId: streamRef.current?.id,
                streamActive: streamRef.current?.active,
                streamsMatch: videoRef.current.srcObject?.id === streamRef.current?.id
              });
            }
          }, 500);
        } else {
          console.error('❌ Video element or stream not available after render');
        }
      }, 100);

      // Set up SocketIO connection
      await setupSocketIOConnection();

    } catch (err) {
      console.error('❌ Error starting video:', err);
      setError(`Failed to access camera: ${err.message}`);
      setVideoStatus('Error');

      // Cleanup on error
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      }
      setIsVideoStarted(false);
    }
  };

  const handleStopVideo = useCallback(() => {
    // console.log('🛑 handleStopVideo called');
    // console.trace('🛑 Stop video called from:');

    // Stop detection if active
    if (isDetectingRef.current) {
      handleStopDetection();
    }

    // Close SocketIO connection
    if (socketRef.current) {
      console.log('🔌 Closing SocketIO connection...');
      socketRef.current.disconnect();
      socketRef.current = null;
    }

    // Stop frame processing
    if (frameProcessingIntervalRef.current) {
      console.log('🖼️ Stopping frame processing...');
      clearInterval(frameProcessingIntervalRef.current);
      frameProcessingIntervalRef.current = null;
    }

    // Stop video stream
    if (streamRef.current) {
      webcamUtils.stopStream(streamRef.current);
      streamRef.current = null;
    }

    // Reset video element
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setIsVideoStarted(false);
    setIsDetecting(false);
    setVideoStatus('Stopped');
    setDetectedPerson(null);
    setError(null);
    setConnectionState('disconnected');
  }, []);

  // Pure SocketIO setup for frame processing
  const setupSocketIOConnection = async () => {
    console.log('🔌 Setting up SocketIO connection...');

    try {
      // Connect to SocketIO server
      const socket = io('http://localhost:8000');
      socketRef.current = socket;

      console.log('🔌 SocketIO client created, waiting for connection...');

      // Handle SocketIO events
      socket.on('connect', () => {
        console.log('🔌 Connected to SocketIO server:', socket.id);
        setConnectionState('connected');

        // Start detection when connected
        console.log('🎯 Emitting start_detection...');
        socket.emit('start_detection', {});

        console.log('🎯 Setting isDetecting to true...');
        setIsDetecting(true);
        isDetectingRef.current = true;

        // Start frame processing
        console.log('🖼️ About to start frame processing...');
        startFrameProcessing();
      });

      socket.on('disconnect', () => {
        console.log('🔌 Disconnected from SocketIO server');
        setConnectionState('disconnected');

        // Stop frame processing
        if (frameProcessingIntervalRef.current) {
          clearInterval(frameProcessingIntervalRef.current);
          frameProcessingIntervalRef.current = null;
        }
      });

      // Handle face detection results from SocketIO
      socket.on('face_detection_result', (data) => {
        // console.log('🔍 Received face detection results:', data);
        handleDetectionResult(data);
      });

      socket.on('detection_started', (data) => {
        console.log('🎯 Detection started:', data);
      });

      socket.on('detection_stopped', (data) => {
        console.log('🛑 Detection stopped:', data);
      });

      socket.on('detection_error', (error) => {
        console.error('❌ Detection error:', error);
        setError(`Detection error: ${error.error}`);
      });

      socket.on('connect_error', (error) => {
        console.error('🔌 SocketIO connection error:', error);
        setError(`Connection error: ${error.message}`);
        setConnectionState('error');
      });

      socket.on('error', (error) => {
        console.error('🔌 SocketIO error:', error);
      });

      console.log('🔌 SocketIO setup complete');
    } catch (error) {
      console.error('🔌 Failed to setup SocketIO:', error);
      setError(`Connection setup failed: ${error.message}`);
    }
  };

  // Start processing frames from video element
  const startFrameProcessing = () => {
    if (frameProcessingIntervalRef.current) {
      clearInterval(frameProcessingIntervalRef.current);
    }

    console.log('🖼️ Starting frame processing...');

    frameProcessingIntervalRef.current = setInterval(() => {
      // console.log('⏰ Frame processing interval tick:', {
      //   videoExists: !!videoRef.current,
      //   socketExists: !!socketRef.current,
      //   isDetecting: isDetectingRef.current,
      //   videoReadyState: videoRef.current?.readyState
      // });

      if (videoRef.current && socketRef.current && isDetectingRef.current) {
        captureAndSendFrame();
      }
    }, 100); // Process 10 frames per second for smoother streaming
  };

  // Capture frame from video element and send via SocketIO
  const captureAndSendFrame = () => {
    try {
      const video = videoRef.current;
      if (!video || video.readyState !== 4) {
        console.log('📹 Video not ready for frame capture:', {
          exists: !!video,
          readyState: video?.readyState
        });
        return;
      }

      // Create canvas to capture frame
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      const ctx = canvas.getContext('2d');

      // Draw current video frame to canvas
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      // Convert to base64
      const frameData = canvas.toDataURL('image/jpeg', 0.8);

      // console.log('📤 Sending frame for processing:', {
      //   width: canvas.width,
      //   height: canvas.height,
      //   dataLength: frameData.length
      // });

      // Send frame to backend for processing
      socketRef.current.emit('process_frame', {
        frame: frameData
      });

    } catch (error) {
      console.error('🖼️ Error capturing frame:', error);
    }
  };

  // Handle detection results for UI updates
  const handleDetectionResult = (data) => {
    // console.log('🔍 Received detection results:', data);

    if (data.faces && data.faces.length > 0) {
      // Find the best recognition result
      const recognizedFaces = data.faces.filter(face => face.recognized);
      const bestMatch = recognizedFaces.length > 0 ?
        recognizedFaces.reduce((best, current) =>
          current.match_confidence > best.match_confidence ? current : best
        ) : null;

      if (bestMatch) {
        const detectedPerson = {
          id: bestMatch.student_id,
          name: bestMatch.student_name,
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

    // Draw detection overlays on canvas using backend coordinates
    drawDetectionOverlays(data.faces || []);
  };

  // Draw detection overlays using canvas
  const drawDetectionOverlays = (faces) => {
    if (!canvasRef.current || !videoRef.current) {
      console.log('🎨 Canvas or video not available for drawing');
      return;
    }

    const canvas = canvasRef.current;
    const video = videoRef.current;
    const ctx = canvas.getContext('2d');

    // Set canvas size to match video
    canvas.width = video.videoWidth || video.clientWidth;
    canvas.height = video.videoHeight || video.clientHeight;

    // console.log('🎨 Drawing overlays:', {
    //   facesCount: faces.length,
    //   canvasSize: { width: canvas.width, height: canvas.height },
    //   videoSize: { width: video.videoWidth, height: video.videoHeight }
    // });

    // Clear previous overlays
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw bounding boxes and labels
    faces.forEach((face) => {
      //console.log(`🎨 Drawing face ${index}:`, face);

      const [x1, y1, x2, y2] = face.bbox;
      const width = x2 - x1;
      const height = y2 - y1;

      // Scale coordinates to canvas size (should be 1:1 since we're using the video dimensions)
      const scaleX = canvas.width / (video.videoWidth || video.clientWidth);
      const scaleY = canvas.height / (video.videoHeight || video.clientHeight);

      const scaledX = x1 * scaleX;
      const scaledY = y1 * scaleY;
      const scaledWidth = width * scaleX;
      const scaledHeight = height * scaleY;

      // console.log(`🎨 Drawing box at:`, {
      //   original: { x1, y1, x2, y2, width, height },
      //   scaled: { x: scaledX, y: scaledY, width: scaledWidth, height: scaledHeight }
      // });

      // Draw bounding box
      ctx.strokeStyle = face.recognized ? '#00ff00' : '#ff0000';
      ctx.lineWidth = 3;
      ctx.strokeRect(scaledX, scaledY, scaledWidth, scaledHeight);

      // Draw label background
      if (face.recognized) {
        const label = face.student_name;
        const confidence = Math.round(face.match_confidence * 100);

        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect(scaledX, scaledY - 30, scaledWidth, 25);

        // Draw text
        ctx.fillStyle = '#ffffff';
        ctx.font = '24px Arial';
        ctx.fillText(`${label} (${confidence}%)`, scaledX + 5, scaledY - 10);
      } else {
        // Draw "Unknown" label for unrecognized faces
        ctx.fillStyle = 'rgba(255, 0, 0, 0.7)';
        ctx.fillRect(scaledX, scaledY - 30, scaledWidth, 25);

        ctx.fillStyle = '#ffffff';
        ctx.font = '14px Arial';
        ctx.fillText('Unknown', scaledX + 5, scaledY - 10);
      }
    });
  };

  const handleStopDetection = () => {
    setIsDetecting(false);
    isDetectingRef.current = false;
    setDetectedPerson(null);

    // Stop frame processing
    if (frameProcessingIntervalRef.current) {
      clearInterval(frameProcessingIntervalRef.current);
      frameProcessingIntervalRef.current = null;
    }

    // Tell backend to stop detection
    if (socketRef.current) {
      socketRef.current.emit('stop_detection', {});
    }
  };


  // Cleanup on unmount
  useEffect(() => {
    return () => {
      console.log('🧹 Component cleanup triggered');
      handleStopVideo();
    };
  }, [handleStopVideo]);

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
                <Title order={4} c="white">
                  Camera Feed
                </Title>
                <Badge
                  color={connectionState === 'connected' ? 'green' : connectionState === 'connecting' ? 'yellow' : 'red'}
                  variant="filled"
                  size="lg"
                >
                  {connectionState === 'connected' ? 'SocketIO Connected' :
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
                  backgroundColor: isVideoStarted ? '#000' : 'rgb(225, 235, 255)',
                  border: '2px solid white',
                  borderRadius: '8px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  position: 'relative',
                }}
              >
                {!isVideoStarted ? (
                  <Group>
                    <IconVideoOff size={48} color="white" />
                    <Text size="lg" c="white">
                      Camera Feed Stopped
                    </Text>
                  </Group>
                ) : (
                  <Box style={{ position: 'relative', width: '100%', height: '100%' }}>
                    {/* HTML5 video stream - smooth and efficient */}
                    <video
                      ref={videoRef}
                      autoPlay
                      muted
                      playsInline
                      style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                        borderRadius: '6px',
                        display: 'block'
                      }}
                    />

                    {/* Canvas overlay for backend-calculated detection boxes */}
                    <canvas
                      ref={canvasRef}
                      style={{
                        width: '100%',
                        height: '100%',
                        borderRadius: '6px',
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        zIndex: 2,
                        pointerEvents: 'none'
                      }}
                    />

                    {/* Detection Overlay */}
                    {isDetecting && detectedPerson && (
                      <Box
                        style={{
                          position: 'absolute',
                          top: 20,
                          left: 20,
                          backgroundColor: 'rgba(0, 36, 61, 0.9)',
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
                  disabled={isVideoStarted}
                  style={{
                    backgroundColor: 'rgb(0, 36, 61)',
                    '&:hover': { backgroundColor: 'rgb(0, 170, 127)' },
                  }}
                >
                  Start Camera & Detection
                </Button>

                <Button
                  leftSection={<IconVideoOff size={20} />}
                  onClick={handleStopVideo}
                  disabled={!isVideoStarted}
                  color="red"
                  variant="filled"
                >
                  Stop Camera
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
              <Title order={5} c="white" mb="md">
                Current Detection
              </Title>

              {detectedPerson ? (
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={600} c="white">Name:</Text>
                    <Text c="white">{detectedPerson.name}</Text>
                  </Group>
                  <Group justify="space-between">
                    <Text fw={600} c="white">ID:</Text>
                    <Text c="white">{detectedPerson.id}</Text>
                  </Group>
                  <Group justify="space-between">
                    <Text fw={600} c="white">Confidence:</Text>
                    <Badge
                      color={detectedPerson.confidence > 80 ? 'green' : 'orange'}
                    >
                      {detectedPerson.confidence}%
                    </Badge>
                  </Group>
                </Stack>
              ) : (
                <Text c="white" ta="center" py="md">
                  {isDetecting ? 'Scanning for faces...' : 'No detection active'}
                </Text>
              )}
            </Card>

            {/* Detection History */}
            <Card shadow="md" radius="md" withBorder>
              <Title order={5} c="white" mb="md">
                Recent Detections
              </Title>

              <Stack gap="xs" style={{ maxHeight: 300, overflowY: 'auto' }}>
                {detectionHistory.length === 0 ? (
                  <Text c="white" ta="center" py="md">
                    No recent detections
                  </Text>
                ) : (
                  detectionHistory.map((detection, index) => (
                    <Paper key={index} p="xs" withBorder>
                      <Group justify="space-between" gap="xs">
                        <Box style={{ flex: 1 }}>
                          <Text size="sm" fw={600} c="white">
                            {detection.name}
                          </Text>
                          <Text size="xs" c="white">
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