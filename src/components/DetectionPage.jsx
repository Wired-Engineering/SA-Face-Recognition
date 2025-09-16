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
} from '@mantine/core';
import {
  IconVideo,
  IconVideoOff,
  IconAlertCircle,
  IconHome,
} from '@tabler/icons-react';
import apiService, { webcamUtils } from '../services/api';
import { io } from 'socket.io-client';
import { openWelcomePopup } from '../services/welcomePopup';

export function DetectionPage({ onDetection }) {
  const theme = useMantineTheme();
  const [isVideoStarted, setIsVideoStarted] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [detectedPerson, setDetectedPerson] = useState(null);
  const [detectionHistory, setDetectionHistory] = useState([]);
  const [videoStatus, setVideoStatus] = useState('Stopped');
  const [error, setError] = useState(null);
  const [isRtspSource, setIsRtspSource] = useState(false);
  const videoRef = useRef(null);
  const rtspImageRef = useRef(null);
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
      console.log('🎥 Starting video...');

      // Load saved camera settings
      const cameraSettings = await apiService.getCameraSettings();
      console.log('📷 Loaded camera settings:', cameraSettings);

      let constraints = {
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30 }
        },
        audio: false
      };

      // Apply saved camera settings
      if (cameraSettings.success || cameraSettings.source) {
        if (cameraSettings.source === 'rtsp') {
          // RTSP camera - use HTTP video stream with overlays from backend
          console.log('📡 RTSP camera selected, using ffmpeg stream with overlays');

          // Set RTSP mode
          setIsRtspSource(true);

          // Set video source to ffmpeg stream with overlays endpoint
          setIsVideoStarted(true);
          setVideoStatus('Connecting to RTSP...');

          // Set up RTSP image stream with overlays after state update
          setTimeout(() => {
            if (rtspImageRef.current) {
              rtspImageRef.current.src = '/api/rtsp/stream-with-overlay';
              console.log('📡 RTSP stream source set to /api/rtsp/stream-with-overlay');
            }
          }, 100);

          // Use existing Socket.IO connection for welcome screen recognition events only
          await setupSocketIOConnection();
          return; // Skip getUserMedia for RTSP
        } else if (cameraSettings.device_id && cameraSettings.source === 'device') {
          // Specific camera device
          constraints.video.deviceId = { exact: cameraSettings.device_id };
          console.log('📹 Using specific camera:', cameraSettings.device_id);
          setIsRtspSource(false);
        } else {
          setIsRtspSource(false);
        }
        // Otherwise use default camera
      } else {
        setIsRtspSource(false);
      }

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

  const handleStopVideo = useCallback(async () => {
    // console.log('🛑 handleStopVideo called');
    // console.trace('🛑 Stop video called from:');

    // Stop detection if active
    if (isDetectingRef.current) {
      handleStopDetection();
    }

    // Stop RTSP streams if using RTSP
    if (isRtspSource) {
      try {
        console.log('🛑 Stopping RTSP streams...');
        await apiService.stopRtspStreams();
        console.log('✅ RTSP streams stopped');
      } catch (error) {
        console.error('❌ Error stopping RTSP streams:', error);
      }
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

        // Start detection (works for both webcam and RTSP)
        console.log('🎯 Emitting start_detection...');
        socket.emit('start_detection', {});

        console.log('🎯 Setting isDetecting to true...');
        setIsDetecting(true);
        isDetectingRef.current = true;

        // Start frame processing (only for webcam, RTSP handles detection and overlays on backend)
        // Check camera source dynamically since Socket.IO connects before RTSP state is set
        apiService.getCameraSettings().then(currentCameraSettings => {
          if (currentCameraSettings.source !== 'rtsp') {
            console.log('🖼️ Starting frame processing for webcam...');
            startFrameProcessing();
          } else {
            console.log('📡 RTSP mode - backend handles detection and overlays, skipping frontend frame processing');
          }
        }).catch(error => {
          console.error('Error checking camera settings:', error);
          // Default to starting frame processing if we can't check
          startFrameProcessing();
        });
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
    }, 33); // Process ~30 frames per second for better responsiveness
  };

  // Capture frame from video element or RTSP image and send via SocketIO
  const captureAndSendFrame = () => {
    try {
      let sourceElement;
      let width, height;

      if (isRtspSource) {
        sourceElement = rtspImageRef.current;
        if (!sourceElement || !sourceElement.complete || sourceElement.naturalWidth === 0) {
          console.log('📹 RTSP image not ready for frame capture:', {
            exists: !!sourceElement,
            complete: sourceElement?.complete,
            naturalWidth: sourceElement?.naturalWidth,
            src: sourceElement?.src
          });
          return;
        }
        width = sourceElement.naturalWidth || 640;
        height = sourceElement.naturalHeight || 480;
      } else {
        sourceElement = videoRef.current;
        if (!sourceElement || sourceElement.readyState !== 4) {
          console.log('📹 Video not ready for frame capture:', {
            exists: !!sourceElement,
            readyState: sourceElement?.readyState
          });
          return;
        }
        width = sourceElement.videoWidth || 640;
        height = sourceElement.videoHeight || 480;
      }

      // Create canvas to capture frame
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');

      // Draw current frame to canvas
      ctx.drawImage(sourceElement, 0, 0, canvas.width, canvas.height);

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

    // Draw detection overlays on canvas ONLY for webcam (RTSP has overlays from backend)
    if (!isRtspSource) {
      drawDetectionOverlays(data.faces || [], data.frame_size);
    }
  };

  // Draw detection overlays using canvas
  const drawDetectionOverlays = (faces, frameSize) => {
    // Skip canvas drawing for RTSP mode - overlays are handled by backend
    if (isRtspSource) {
      return;
    }

    if (!canvasRef.current) {
      console.log('🎨 Canvas not available for drawing');
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');

    // Set canvas size to match the displayed image size (not natural size)
    if (isRtspSource && rtspImageRef.current) {
      const rtspImage = rtspImageRef.current;
      canvas.width = rtspImage.clientWidth || 640;
      canvas.height = rtspImage.clientHeight || 480;
    } else if (videoRef.current) {
      const video = videoRef.current;
      canvas.width = video.videoWidth || video.clientWidth || 640;
      canvas.height = video.videoHeight || video.clientHeight || 480;
    } else {
      console.log('🎨 No video or RTSP image available for drawing');
      return;
    }

    // console.log('🎨 Drawing overlays:', {
    //   facesCount: faces.length,
    //   canvasSize: { width: canvas.width, height: canvas.height },
    //   frameSize: frameSize,
    //   isRtspSource: isRtspSource
    // });

    // Clear previous overlays
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw bounding boxes and labels
    faces.forEach((face) => {
      //console.log(`🎨 Drawing face ${index}:`, face);

      const [x1, y1, x2, y2] = face.bbox;
      const width = x2 - x1;
      const height = y2 - y1;

      // Scale coordinates from backend frame size to displayed canvas size
      let scaleX = 1;
      let scaleY = 1;

      if (isRtspSource && frameSize) {
        // For RTSP, scale from backend frame size to displayed size
        scaleX = canvas.width / frameSize.width;
        scaleY = canvas.height / frameSize.height;
        // console.log('🎨 RTSP scaling:', {
        //   canvasSize: { width: canvas.width, height: canvas.height },
        //   frameSize: frameSize,
        //   scale: { x: scaleX, y: scaleY }
        // });
      } else if (videoRef.current) {
        // For webcam, use video dimensions
        const video = videoRef.current;
        scaleX = canvas.width / (video.videoWidth || video.clientWidth || 640);
        scaleY = canvas.height / (video.videoHeight || video.clientHeight || 480);
      }

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
        const label = face.person_name;
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

  // Cleanup RTSP streams on page unload
  useEffect(() => {
    const handleBeforeUnload = async () => {
      if (isRtspSource) {
        try {
          await apiService.stopRtspStreams();
        } catch (error) {
          console.error('Error stopping RTSP streams on page unload:', error);
        }
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [isRtspSource]);

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
                    {/* HTML5 video stream for webcam */}
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
                        display: isRtspSource ? 'none' : 'block'
                      }}
                    />

                    {/* MJPEG image stream for RTSP */}
                    {isRtspSource && (
                      <img
                        ref={rtspImageRef}
                        alt="RTSP Stream"
                        style={{
                          width: '100%',
                          height: '100%',
                          objectFit: 'cover',
                          borderRadius: '6px',
                          display: 'block'
                        }}
                        onLoad={() => {
                          console.log('📡 RTSP stream loaded successfully');
                          console.log('📡 RTSP image dimensions:', {
                            naturalWidth: rtspImageRef.current?.naturalWidth,
                            naturalHeight: rtspImageRef.current?.naturalHeight,
                            complete: rtspImageRef.current?.complete
                          });
                          setVideoStatus('Connected');
                          setError(null); // Clear any previous errors
                        }}
                        onError={(e) => {
                          console.error('📡 RTSP stream error:', e);
                          console.error('📡 RTSP stream src:', rtspImageRef.current?.src);
                          setError('RTSP stream failed to load. Check the RTSP URL and network connection.');
                          setVideoStatus('Connection Failed');
                        }}
                      />
                    )}

                    {/* Canvas overlay for detection boxes (only for webcam, RTSP has overlays from backend) */}
                    {!isRtspSource && (
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
                    )}

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
                  color="signature"
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