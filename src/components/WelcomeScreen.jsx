import {
  Box,
  Title,
  Text,
  Stack,
  Avatar,
  Paper,
  Loader,
  useMantineTheme,
} from '@mantine/core';
import { IconUser, IconCheck, IconAlertCircle } from '@tabler/icons-react';
import { useEffect, useState, useRef } from 'react';

export function WelcomeScreen({
  isStandalone = false,
  displaySettings = {},
  recognizedUser = null,
  onTimeout = null
}) {
  const theme = useMantineTheme();
  const [timeLeft, setTimeLeft] = useState(displaySettings.timer || 5);
  const [currentUser, setCurrentUser] = useState(recognizedUser);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  // Default display settings
  const settings = {
    backgroundColor: displaySettings.backgroundColor || theme.other.cardBackground,
    fontColor: displaySettings.fontColor || theme.other.textDark,
    timer: displaySettings.timer || 5,
    ...displaySettings
  };

  // WebSocket connection for live data when in standalone mode
  useEffect(() => {
    if (!isStandalone) return;

    const connectWebSocket = () => {
      try {
        // Try to connect to WebSocket for live recognition data
        wsRef.current = new WebSocket('ws://localhost:8000/ws/recognition');

        wsRef.current.onopen = () => {
          console.log('✅ Connected to recognition WebSocket');
          setIsConnected(true);
        };

        wsRef.current.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'recognition' && data.user) {
              setCurrentUser(data.user);
              setLastUpdate(new Date());
              setTimeLeft(settings.timer); // Reset timer on new recognition
            }
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };

        wsRef.current.onclose = () => {
          console.log('❌ WebSocket connection closed');
          setIsConnected(false);

          // Attempt to reconnect after 3 seconds
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('🔄 Attempting to reconnect...');
            connectWebSocket();
          }, 3000);
        };

        wsRef.current.onerror = (error) => {
          console.error('WebSocket error:', error);
          setIsConnected(false);
        };

      } catch (error) {
        console.error('Failed to connect to WebSocket:', error);
        setIsConnected(false);
      }
    };

    // Fallback: Poll for recognition data if WebSocket not available
    const pollForData = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/recognition/latest');
        if (response.ok) {
          const data = await response.json();
          if (data.user && data.timestamp !== lastUpdate?.getTime()) {
            setCurrentUser(data.user);
            setLastUpdate(new Date(data.timestamp));
            setTimeLeft(settings.timer);
          }
        }
      } catch (error) {
        console.error('Failed to poll recognition data:', error);
      }
    };

    connectWebSocket();

    // Fallback polling every 1 second
    const pollInterval = setInterval(pollForData, 1000);

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      clearInterval(pollInterval);
    };
  }, [isStandalone, settings.timer, lastUpdate]);

  // Timer countdown
  useEffect(() => {
    if (timeLeft > 0 && currentUser) {
      const timer = setTimeout(() => {
        setTimeLeft(timeLeft - 1);
      }, 1000);
      return () => clearTimeout(timer);
    } else if (timeLeft === 0 && currentUser) {
      // Clear user data when timer expires
      setCurrentUser(null);
      if (onTimeout) {
        onTimeout();
      }
    }
  }, [timeLeft, currentUser, onTimeout]);

  // Window management for standalone mode
  useEffect(() => {
    if (isStandalone && window.parent !== window) {
      // This is a popup window
      document.title = 'Face Recognition - Welcome Canvas';

      // Auto-close window on timer expiry if no callback is provided
      if (timeLeft === 0 && !onTimeout && currentUser) {
        setTimeout(() => {
          window.close();
        }, 1000);
      }
    }
  }, [isStandalone, timeLeft, onTimeout, currentUser]);

  return (
    <Box
      style={{
        width: '100%',
        minHeight: '100vh',
        backgroundColor: settings.backgroundColor,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px',
        position: 'relative'
      }}
    >
      {/* Connection Status (only in standalone mode) */}
      {isStandalone && (
        <Box
          style={{
            position: 'absolute',
            top: '20px',
            right: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 16px',
            borderRadius: '20px',
            backgroundColor: isConnected ? 'rgba(81, 207, 102, 0.1)' : 'rgba(255, 107, 107, 0.1)',
            border: `1px solid ${isConnected ? '#51cf66' : '#ff6b6b'}`
          }}
        >
          <Box
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor: isConnected ? '#51cf66' : '#ff6b6b'
            }}
          />
          <Text size="sm" c={isConnected ? '#51cf66' : '#ff6b6b'}>
            {isConnected ? 'Live' : 'Offline'}
          </Text>
        </Box>
      )}

      <Paper
        shadow="xl"
        radius="lg"
        p="xl"
        style={{
          backgroundColor: 'white',
          border: `3px solid ${settings.fontColor}`,
          minWidth: '500px',
          textAlign: 'center'
        }}
      >
        {currentUser ? (
          <Stack align="center" gap="xl">
            {/* Success Icon */}
            <Box
              style={{
                width: 80,
                height: 80,
                borderRadius: '50%',
                backgroundColor: '#51cf66',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '20px'
              }}
            >
              <IconCheck size={48} color="white" />
            </Box>

            {/* Welcome Message */}
            <Stack align="center" gap="md">
              <Title
                order={1}
                style={{
                  color: settings.fontColor,
                  fontSize: '3rem',
                  fontWeight: 'bold',
                  margin: 0
                }}
              >
                Welcome
              </Title>

              {/* User Avatar */}
              <Avatar
                size={120}
                radius="xl"
                src={currentUser.photo}
                style={{
                  border: `4px solid ${settings.fontColor}`,
                  margin: '20px 0'
                }}
              >
                <IconUser size={60} />
              </Avatar>

              {/* User Name */}
              <Title
                order={2}
                style={{
                  color: settings.fontColor,
                  fontSize: '2.2rem',
                  fontWeight: 'normal',
                  lineHeight: 1.2,
                  margin: 0
                }}
              >
                {currentUser.name || currentUser.person_name || 'Unknown User'}
              </Title>

              {/* User Details */}
              {(currentUser.personId || currentUser.person_id) && (
                <Text
                  size="xl"
                  style={{
                    color: settings.fontColor,
                    fontSize: '1.3rem',
                    opacity: 0.8
                  }}
                >
                  ID: {currentUser.personId || currentUser.person_id}
                </Text>
              )}

              {currentUser.department && (
                <Text
                  size="lg"
                  style={{
                    color: settings.fontColor,
                    fontSize: '1.1rem',
                    opacity: 0.7
                  }}
                >
                  {currentUser.department}
                </Text>
              )}

              {/* Confidence Score */}
              {currentUser.confidence && (
                <Text
                  size="sm"
                  style={{
                    color: settings.fontColor,
                    opacity: 0.6
                  }}
                >
                  Confidence: {Math.round(currentUser.confidence * 100)}%
                </Text>
              )}
            </Stack>

            {/* Timer Display */}
            {timeLeft > 0 && (
              <Text
                size="sm"
                style={{
                  color: settings.fontColor,
                  opacity: 0.6,
                  marginTop: '30px'
                }}
              >
                Closing in {timeLeft} seconds...
              </Text>
            )}
          </Stack>
        ) : (
          // Waiting for recognition
          <Stack align="center" gap="xl" py="xl">
            {isStandalone ? (
              <>
                <Loader size="xl" color={settings.fontColor} />
                <Title
                  order={2}
                  style={{
                    color: settings.fontColor,
                    fontSize: '1.8rem'
                  }}
                >
                  Waiting for face recognition...
                </Title>
                <Text
                  style={{
                    color: settings.fontColor,
                    opacity: 0.7
                  }}
                >
                  Position yourself in front of the camera
                </Text>
              </>
            ) : (
              <>
                <IconAlertCircle size={64} color={settings.fontColor} style={{ opacity: 0.6 }} />
                <Title
                  order={2}
                  style={{
                    color: settings.fontColor,
                    fontSize: '1.8rem'
                  }}
                >
                  No Recognition Data
                </Title>
                <Text
                  style={{
                    color: settings.fontColor,
                    opacity: 0.7
                  }}
                >
                  This screen will show user information when face recognition occurs
                </Text>
              </>
            )}
          </Stack>
        )}
      </Paper>
    </Box>
  );
}
