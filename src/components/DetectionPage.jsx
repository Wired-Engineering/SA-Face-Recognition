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
  const [isDetecting, setIsDetecting] = useState(false); // eslint-disable-line no-unused-vars
  const [detectedPerson, setDetectedPerson] = useState(null); // eslint-disable-line no-unused-vars
  const [detectionHistory, setDetectionHistory] = useState([]);
  const [videoStatus, setVideoStatus] = useState('Stopped');
  const [error, setError] = useState(null);
  const [actualCameraSource, setActualCameraSource] = useState('default');
  const rtspImageRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null); // For capturing frames
  const frameProcessingIntervalRef = useRef(null);
  const isDetectingRef = useRef(false);
  const [isStreamLoading, setIsStreamLoading] = useState(false);
  const [browserWebcamStream, setBrowserWebcamStream] = useState(null);
  const lastFrameTimeRef = useRef(0);
  const currentBlobUrlRef = useRef(null);
  const [faceDetections, setFaceDetections] = useState([]);
  const videoContainerRef = useRef(null);

  // Handle batch recognition results (multiple users simultaneously)
  const handleBatchRecognitionResult = useCallback((users) => {
    console.log(`🎯 Processing batch recognition with ${users.length} users:`, users);

    if (users.length === 0) return;

    // For the detection page UI, show the user with highest confidence
    const bestUser = users.reduce((best, current) =>
      current.confidence > best.confidence ? current : best
    );

    const detectedPerson = {
      id: bestUser.person_id,
      name: bestUser.person_name || bestUser.name,
      title: bestUser.userTitle,
      confidence: Math.round(bestUser.confidence * 100),
      totalDetected: users.length // Show how many people were detected
    };

    setDetectedPerson(detectedPerson);

    // Add all users to detection history
    const now = new Date().toLocaleString();
    const rawTimestamp = Date.now();

    setDetectionHistory(prev => {
      const newEntries = users.map(user => ({
        id: user.person_id,
        name: user.person_name || user.name,
        title: user.userTitle,
        confidence: Math.round(user.confidence * 100),
        timestamp: now,
        rawTimestamp: rawTimestamp
      }));

      // Combine with existing history and keep last 10
      return [...newEntries, ...prev].slice(0, 10);
    });

    onDetection?.(detectedPerson);
  }, [onDetection]);

  // Handle individual recognition results (legacy support)
  const handleIndividualRecognitionResult = useCallback((user) => {
    console.log('🎯 Processing individual recognition:', user);

    const detectedPerson = {
      id: user.person_id,
      name: user.person_name || user.name,
      title: user.userTitle,
      confidence: Math.round(user.confidence * 100),
      totalDetected: 1
    };

    setDetectedPerson(detectedPerson);

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
        }, ...prev.slice(0, 9)];
      }
      return prev;
    });

    onDetection?.(detectedPerson);
  }, [onDetection]);

  // Handle detection results for UI updates (welcome screens and UI state only)
  const handleDetectionResult = useCallback((data) => {
    // console.log('🔍 Received detection results:', data);

    // Update UI state for detection results
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

  // Handle binary frame processing results
  const handleBinaryFrameResult = useCallback((data) => {
    // console.log('🔍 Received binary frame results:', data);

    // Update face detections for visual overlays
    if (data.faces && data.faces.length > 0) {
      setFaceDetections(data.faces);
      // Also process faces for UI display
      handleDetectionResult({ faces: data.faces });
    } else {
      setFaceDetections([]);
      setDetectedPerson(null);
    }
  }, [handleDetectionResult]);
  const handleStopDetection = useCallback((adminStop = false) => {
    setIsDetecting(false);
    isDetectingRef.current = false;
    setDetectedPerson(null);

    // Stop frame processing
    if (frameProcessingIntervalRef.current) {
      cancelAnimationFrame(frameProcessingIntervalRef.current);
      frameProcessingIntervalRef.current = null;
    }

    // Tell backend to stop detection
    if (isConnected) {
      emit('stop_detection', { admin_stop: adminStop });
    }
  }, [isConnected, emit]);
  // Browser webcam capture and frame processing
  const startBrowserWebcam = useCallback(async (deviceId = null) => {
    try {
      console.log('📹 Starting browser webcam capture...', deviceId ? `Device: ${deviceId}` : 'Default device');

      // Check if getUserMedia is available
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Camera access is not supported in this browser. Please use a modern browser with HTTPS.');
      }

      // Check if running over HTTPS (required for camera access in most browsers)
      if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
        throw new Error('Camera access requires HTTPS. Please access this site using HTTPS for camera functionality.');
      }

      // Check camera permissions first
      try {
        const permission = await navigator.permissions.query({ name: 'camera' });
        console.log('📹 Camera permission status:', permission.state);

        if (permission.state === 'denied') {
          throw new Error('Camera access has been denied. Please enable camera permissions in your browser settings and reload the page.');
        }
      } catch {
        // Permissions API not supported in all browsers, continue with getUserMedia
        console.log('📹 Permissions API not supported, proceeding with getUserMedia');
      }

      // Build constraints based on device selection
      const constraints = {
        video: {
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 30 }
        },
        audio: false
      };

      // Add specific device ID if provided
      if (deviceId && deviceId !== 'default') {
        constraints.video.deviceId = { exact: deviceId };
      }

      // Get user media for webcam - this will prompt for permission if not granted
      setVideoStatus('Requesting camera permission...');
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia(constraints);
      } catch (constraintError) {
        // If specific device fails, try again with default device
        if (constraintError.name === 'OverconstrainedError' && deviceId && deviceId !== 'default') {
          console.warn('📹 Specific device failed, falling back to default camera:', constraintError);

          // Clear the invalid device settings to prevent future auto-restart issues
          try {
            await apiService.updateCameraSettings('default', null, null);
            console.log('🔄 Cleared invalid device settings, set to default camera');
          } catch (settingsError) {
            console.warn('Failed to clear invalid camera settings:', settingsError);
          }

          const fallbackConstraints = {
            video: {
              width: { ideal: 640 },
              height: { ideal: 480 },
              frameRate: { ideal: 30 }
            },
            audio: false
          };
          stream = await navigator.mediaDevices.getUserMedia(fallbackConstraints);
        } else {
          throw constraintError;
        }
      }

      setBrowserWebcamStream(stream);

      // Set video element source
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await new Promise((resolve) => {
          videoRef.current.onloadedmetadata = () => {
            videoRef.current.play();
            resolve();
          };
        });
      }

      // Start frame processing
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');

      const processFrame = () => {
        if (!isDetectingRef.current || !videoRef.current || !canvas || !ctx) {
          return;
        }

        // Throttle frame processing to prevent overwhelming the network
        const now = Date.now();
        if (now - lastFrameTimeRef.current < 100) { // Max 10 FPS
          return;
        }
        lastFrameTimeRef.current = now;

        // Draw video frame to canvas
        canvas.width = videoRef.current.videoWidth || 640;
        canvas.height = videoRef.current.videoHeight || 480;
        ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);

        // Convert to blob and send as binary to backend
        canvas.toBlob((blob) => {
          if (blob) {
            // Send binary blob directly via Socket.IO
            emit('process_frame_binary', {
              frame: blob,
              width: canvas.width,
              height: canvas.height
            });
          }
        }, 'image/jpeg', 0.8);
      };

      // Process frames using requestAnimationFrame with throttling
      const frameLoop = () => {
        processFrame();
        if (isDetectingRef.current) {
          frameProcessingIntervalRef.current = requestAnimationFrame(frameLoop);
        }
      };
      frameLoop();

      console.log('✅ Browser webcam capture started');
      setVideoStatus('Browser Webcam Active');
      setIsStreamLoading(false);

    } catch (error) {
      console.error('❌ Error starting browser webcam:', error);
      setIsStreamLoading(false);
      setVideoStatus('Error');

      // Provide specific error messages for common permission issues
      let errorMessage = error.message;

      if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
        errorMessage = 'Camera access denied. Please click "Allow" when prompted for camera permission, or check your browser settings to enable camera access for this site.';
      } else if (error.name === 'NotFoundError' || error.name === 'DeviceNotFoundError') {
        errorMessage = 'No camera found. Please ensure a camera is connected and try again.';
      } else if (error.name === 'NotReadableError' || error.name === 'TrackStartError') {
        errorMessage = 'Camera is already in use by another application. Please close other applications using the camera and try again.';
      } else if (error.name === 'OverconstrainedError' || error.name === 'ConstraintNotSatisfiedError') {
        errorMessage = 'Selected camera does not support the required settings. Camera settings have been reset to default.';

        // Clear detection state to prevent auto-restart loop
        if (isDetectingRef.current) {
          handleStopDetection(true);
        }
        setIsVideoStarted(false);
      } else if (error.name === 'NotSupportedError') {
        errorMessage = 'Camera access is not supported. Please use HTTPS and a modern browser.';
      } else if (error.name === 'SecurityError') {
        errorMessage = 'Camera access blocked for security reasons. Please ensure you are using HTTPS and try again.';
      }

      setError(`Failed to access camera: ${errorMessage}`);
      throw error;
    }
  }, [emit, handleStopDetection]);

  const stopBrowserWebcam = useCallback(() => {
    console.log('🛑 Stopping browser webcam...');

    // Stop the media stream
    if (browserWebcamStream) {
      browserWebcamStream.getTracks().forEach(track => track.stop());
      setBrowserWebcamStream(null);
    }

    // Clear video element
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    // Stop frame processing
    if (frameProcessingIntervalRef.current) {
      cancelAnimationFrame(frameProcessingIntervalRef.current);
      frameProcessingIntervalRef.current = null;
    }

    // Clean up current blob URL
    if (currentBlobUrlRef.current) {
      URL.revokeObjectURL(currentBlobUrlRef.current);
      currentBlobUrlRef.current = null;
    }

    console.log('✅ Browser webcam stopped');
  }, [browserWebcamStream]);

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
        } else {
          // All other camera sources - use browser getUserMedia with Socket.IO processing
          const source = cameraSettings.source || 'default';
          console.log('📹 Camera selected:', source, 'using browser getUserMedia with Socket.IO processing');

          // Set browser webcam mode
          setActualCameraSource('browser');
          setIsVideoStarted(true);
          setVideoStatus('Starting camera...');
          setIsStreamLoading(true);

          // Set up Socket.IO connection first
          await setupSocketIOConnection();

          // Start browser webcam capture with specific device if not default
          let deviceIdToUse = null;
          if (cameraSettings.source === 'device' && cameraSettings.device_id) {
            deviceIdToUse = cameraSettings.device_id;
            console.log('📹 Using specific device ID:', deviceIdToUse);
          }

          await startBrowserWebcam(deviceIdToUse);
          return;
        }
      }

    } catch (err) {
      console.error('❌ Error starting video:', err);
      setError(`Failed to start camera: ${err.message}`);
      setVideoStatus('Error');
      setIsVideoStarted(false);
    }
  }, [setupSocketIOConnection, startBrowserWebcam]);

  const handleStopVideo = useCallback(async () => {
    // console.log('🛑 handleStopVideo called');
    // console.trace('🛑 Stop video called from:');

    // Clear the stream image source immediately to stop camera usage
    if (rtspImageRef.current) {
      console.log('🖼️ Clearing RTSP image source immediately');
      rtspImageRef.current.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'; // 1x1 transparent GIF
      rtspImageRef.current.onload = null;
      rtspImageRef.current.onerror = null;
    }

    // Stop detection if active (admin explicit stop)
    if (isDetectingRef.current) {
      handleStopDetection(true);
    }

    // Stop backend streams or browser webcam based on source
    console.log('🔍 Debug stop - actualCameraSource:', actualCameraSource);
    try {
      if (actualCameraSource === 'browser') {
        console.log('🛑 Stopping browser webcam...');
        stopBrowserWebcam();
        // Also stop backend webcam streams to release camera completely
        try {
          await apiService.stopWebcamStreams();
          console.log('✅ Backend webcam streams stopped');
        } catch (error) {
          console.warn('⚠️ Error stopping backend webcam streams:', error);
        }
        console.log('✅ Browser webcam stopped');
      } else if (actualCameraSource === 'rtsp') {
        console.log('🛑 Stopping RTSP streams...');
        await apiService.stopRtspStreams();
        console.log('✅ RTSP streams stopped');
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


    setIsVideoStarted(false);
    setIsDetecting(false);
    setVideoStatus('Stopped');
    setDetectedPerson(null);
    setError(null);
    setIsStreamLoading(false);
  }, [actualCameraSource, disconnect, handleStopDetection, stopBrowserWebcam]);


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

    // Handle binary frame processing results (browser webcam)
    const cleanupBinaryFrameResult = on('frame_processed_binary', (data) => {
      handleBinaryFrameResult(data);
    });

    // Handle face detection results (RTSP and other sources)
    const cleanupFaceDetectionResult = on('face_detection_result', (data) => {
      // For RTSP sources, update detection overlays and UI state
      if (actualCameraSource === 'rtsp') {
        if (data.faces && data.faces.length > 0) {
          setFaceDetections(data.faces);
          handleDetectionResult({ faces: data.faces });
        } else {
          setFaceDetections([]);
          setDetectedPerson(null);
        }
      }
    });

    // Handle recognition results from all sources (batch and individual)
    const cleanupRecognitionResult = on('recognition_result', (data) => {
      console.log('🎯 Recognition result received on DetectionPage:', data);

      if (data.type === 'batch_recognition' && data.users && Array.isArray(data.users)) {
        // Handle batch recognition (multiple users simultaneously)
        // Only update UI for new detections, but always process for welcome screen
        if (data.is_new !== false) {  // Treat undefined as new for backward compatibility
          handleBatchRecognitionResult(data.users);
        }
      } else if (data.type === 'recognition' && data.user) {
        // Handle individual recognition (legacy support)
        handleIndividualRecognitionResult(data.user);
      }
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
      cleanupBinaryFrameResult?.();
      cleanupFaceDetectionResult?.();
      cleanupRecognitionResult?.();
      cleanupDetectionStarted?.();
      cleanupDetectionStopped?.();
      cleanupDetectionError?.();
      cleanupError?.();
    };
  }, [isConnected, on, handleBinaryFrameResult, handleDetectionResult, handleBatchRecognitionResult, handleIndividualRecognitionResult, actualCameraSource]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      console.log('🧹 Component cleanup triggered - preserving detection state');

      // IMPORTANT: Do NOT call disconnect() here to preserve detection state
      // The SocketProvider will handle disconnection, but the backend detection should continue

      // Only clean up local UI state
      setIsVideoStarted(false);
      setIsDetecting(false);

      // Clean up blob URL on unmount
      if (currentBlobUrlRef.current) {
        URL.revokeObjectURL(currentBlobUrlRef.current);
        currentBlobUrlRef.current = null;
      }

      console.log('🔄 Detection should continue running independently for welcome screens');
    };
  }, []); // Empty dependency array - only run on mount/unmount

  // Note: Removed automatic stream cleanup on page unload to preserve detection state
  // Detection should persist across admin page refreshes for welcome screens
  // Only explicit admin "Stop Video" should stop detection

  return (
    <Box style={{ width: '100%', minHeight: '100%' }}>
      {/* Hidden canvas for browser webcam frame capture */}
      <canvas
        ref={canvasRef}
        style={{ display: 'none' }}
      />

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

                    {/* Show MJPEG stream only for RTSP sources */}
                    {actualCameraSource === 'rtsp' && (
                      <Box
                        ref={videoContainerRef}
                        style={{
                          position: 'relative',
                          width: '100%',
                          height: '100%'
                        }}
                      >
                        <img
                          ref={rtspImageRef}
                          alt="RTSP Camera Stream"
                          style={{
                            width: '100%',
                            height: '100%',
                            objectFit: 'cover',
                            borderRadius: '6px',
                            display: 'block'
                          }}
                          onLoad={() => {
                            console.log('📡 RTSP stream loaded successfully');
                            setVideoStatus('RTSP Connected');
                            setError(null);
                            setIsStreamLoading(false);
                          }}
                          onError={(e) => {
                            console.error('📡 RTSP stream error:', e);
                            setError('RTSP stream failed to load. Check camera connection.');
                            setVideoStatus('RTSP Connection Failed');
                            setIsStreamLoading(false);
                          }}
                        />

                        {/* Face detection overlays for RTSP (optional - backend already draws them) */}
                        {/* Uncomment if you want additional CSS overlays on top of backend overlays */}
                        {/* {faceDetections.map((face, index) => {
                          // Same overlay logic as browser webcam
                        })} */}
                      </Box>
                    )}

                    {/* Show live video for browser webcam */}
                    {actualCameraSource === 'browser' && (
                      <Box
                        ref={videoContainerRef}
                        style={{
                          position: 'relative',
                          width: '100%',
                          height: '100%'
                        }}
                      >
                        <video
                          ref={videoRef}
                          autoPlay
                          playsInline
                          muted
                          style={{
                            width: '100%',
                            height: '100%',
                            objectFit: 'cover',
                            borderRadius: '6px',
                            display: 'block'
                          }}
                        />

                        {/* Face detection overlays */}
                        {faceDetections.map((face, index) => {
                          if (!face.bbox || !videoContainerRef.current || !videoRef.current) return null;

                          const container = videoContainerRef.current.getBoundingClientRect();
                          const video = videoRef.current;

                          // Calculate scaling based on video display size vs original frame size
                          const scaleX = container.width / (video.videoWidth || 640);
                          const scaleY = container.height / (video.videoHeight || 480);

                          const [x1, y1, x2, y2] = face.bbox;
                          const width = (x2 - x1) * scaleX;
                          const height = (y2 - y1) * scaleY;
                          const left = x1 * scaleX;
                          const top = y1 * scaleY;

                          const isRecognized = face.recognized;
                          const color = isRecognized ? '#00ff00' : '#ff0000';

                          // Determine label text
                          const label = isRecognized
                            ? `${face.person_name} (${Math.round(face.match_confidence * 100)}%)`
                            : 'Unknown';

                          return (
                            <Box
                              key={index}
                              style={{
                                position: 'absolute',
                                left: `${left}px`,
                                top: `${top}px`,
                                width: `${width}px`,
                                height: `${height}px`,
                                border: `2px solid ${color}`,
                                borderRadius: '2px',
                                pointerEvents: 'none',
                                zIndex: 10
                              }}
                            >
                              {/* Label with background rectangle (like RTSP) */}
                              <Box
                                style={{
                                  position: 'absolute',
                                  top: '-32px',
                                  left: '0',
                                  backgroundColor: color,
                                  color: 'white',
                                  padding: '4px 8px',
                                  fontSize: '14px',
                                  fontWeight: '700',
                                  fontFamily: 'Arial, sans-serif',
                                  whiteSpace: 'nowrap',
                                  borderRadius: '0px',
                                  textShadow: '1px 1px 1px rgba(0,0,0,0.8)',
                                  minHeight: '20px',
                                  display: 'flex',
                                  alignItems: 'center'
                                }}
                              >
                                {label}
                              </Box>
                            </Box>
                          );
                        })}
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

              {/* Camera Permission Info */}
              {!isVideoStarted && !isStreamLoading && (
                <Text size="xs" c="dimmed" ta="center" mt="sm">
                  📹 Camera access is required for face detection.
                  {location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1' && (
                    <span> HTTPS connection required.</span>
                  )}
                  <br />
                  Please allow camera permission if prompted.
                </Text>
              )}

            </Stack>
          </Card>
        </Grid.Col>

        {/* Detection Info Section */}
        <Grid.Col span={3}>
          <Stack gap="md">

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