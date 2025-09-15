import { useState, useEffect } from 'react';
import {
  AppShell,
  Group,
  Title,
  Button,
  Text,
  Stack,
} from '@mantine/core';
import {
  IconVideo,
  IconHome,
  IconUserPlus,
  IconSettings,
  IconLogout,
  IconUser,
} from '@tabler/icons-react';
import { LoginPage } from './LoginPage';
import { RegistrationPage } from './RegistrationPage';
import { SettingsPage } from './SettingsPage';
import { DetectionPage } from './DetectionPage';
import { WelcomeScreen } from './WelcomeScreen';
import { openWelcomePopup } from '../services/welcomePopup';

export function MainAppShell() {
  const [activeView, setActiveView] = useState('login');
  const [loggedUser, setLoggedUser] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Restore auth state from localStorage on mount
  useEffect(() => {
    const savedAuthState = localStorage.getItem('authState');
    if (savedAuthState) {
      try {
        const { isAuthenticated, userName, view } = JSON.parse(savedAuthState);
        if (isAuthenticated && userName) {
          setLoggedUser(userName);
          setIsAuthenticated(true);
          setActiveView(view || 'welcome');
        }
      } catch (error) {
        console.error('Failed to restore auth state:', error);
        localStorage.removeItem('authState');
      }
    }
  }, []);

  // Save auth state to localStorage when it changes
  const saveAuthState = (isAuthenticated, userName, view) => {
    if (isAuthenticated) {
      localStorage.setItem('authState', JSON.stringify({
        isAuthenticated,
        userName,
        view
      }));
    } else {
      localStorage.removeItem('authState');
    }
  };

  const navigationButtons = [
    {
      id: 'detection',
      label: 'Live Detection',
      icon: <IconVideo size={20} />,
      color: 'blue',
    },
    {
      id: 'welcome',
      label: 'Welcome Screen',
      icon: <IconHome size={20} />,
      color: 'green',
    },
    {
      id: 'register',
      label: 'Register',
      icon: <IconUserPlus size={20} />,
      color: 'orange',
    },
    {
      id: 'settings',
      label: 'Settings',
      icon: <IconSettings size={20} />,
      color: 'gray',
    },
  ];

  return (
    <AppShell
      header={{ height: 80 }}
      padding={0}
      styles={{
        main: {
          backgroundColor: 'rgb(225, 235, 255)',
          minHeight: '100vh',
          padding: 0,
          width: '100vw',
        },
        header: {
          backgroundColor: 'rgb(0, 36, 61)',
          border: '2px solid white',
          borderRadius: '15px',
          margin: '0',
        },
      }}
    >
      <AppShell.Header>
        <Group justify="space-between" h="100%" px="md">
          <Group>
            <Title
              order={2}
              c="white"
              style={{
                fontFamily: 'Sitka',
                fontSize: '18px',
                fontWeight: 'normal',
              }}
            >
              Signature Aviation
            </Title>
          </Group>

          {/* Only show navigation when authenticated */}
          {isAuthenticated && (
            <>
              <Group gap="xs">
                {navigationButtons.map((btn) => (
                  <Button
                    key={btn.id}
                    leftSection={btn.icon}
                    variant="subtle"
                    color="white"
                    onClick={() => {
                      if (btn.id === 'welcome') {
                        // Open welcome popup instead of navigating
                        const savedSettings = localStorage.getItem('faceRecognitionDisplaySettings');
                        let displaySettings = {
                          backgroundColor: '#E1EBFF',
                          fontColor: '#00243D',
                          timer: 5
                        };

                        if (savedSettings) {
                          try {
                            displaySettings = { ...displaySettings, ...JSON.parse(savedSettings) };
                          } catch (e) {
                            console.warn('Failed to parse display settings:', e);
                          }
                        }

                        console.log('🪟 Opening welcome popup from header');
                        openWelcomePopup(displaySettings);
                      } else {
                        setActiveView(btn.id);
                        if (loggedUser) {
                          saveAuthState(true, loggedUser, btn.id);
                        }
                      }
                    }}
                    styles={{
                      root: {
                        color: 'white',
                        backgroundColor: 'rgba(0, 170, 127, 0)',
                        border: 'none',
                        borderRadius: '15px',
                        minHeight: '45px',
                        maxHeight: '50px',
                        fontSize: '10pt',
                        fontFamily: 'Tahoma',
                        fontWeight: 'bold',
                        paddingLeft: '5px',
                        paddingRight: '5px',
                        '&:hover': {
                          backgroundColor: 'rgba(255, 255, 255, 0.8)',
                          color: 'rgb(0, 0, 0)',
                        },
                      },
                    }}
                  >
                    {btn.label}
                  </Button>
                ))}

                <Button
                  leftSection={<IconLogout size={20} />}
                  variant="subtle"
                  color="white"
                  onClick={() => {
                    setLoggedUser('');
                    setIsAuthenticated(false);
                    setActiveView('login');
                    saveAuthState(false, '', 'login');
                  }}
                  styles={{
                    root: {
                      color: 'white',
                      backgroundColor: 'rgba(0, 170, 127, 0)',
                      border: 'none',
                      borderRadius: '15px',
                      minHeight: '45px',
                      maxHeight: '50px',
                      fontSize: '10pt',
                      fontFamily: 'Tahoma',
                      fontWeight: 'bold',
                      paddingLeft: '5px',
                      paddingRight: '5px',
                      '&:hover': {
                        backgroundColor: 'rgba(255, 255, 255, 0.8)',
                        color: 'rgb(0, 0, 0)',
                      },
                    },
                  }}
                >
                  Logout
                </Button>
              </Group>

              <Group gap="xs">
                <IconUser size={24} style={{ color: 'white' }} />
                <Text c="white" size="sm">
                  {loggedUser || 'Not logged in'}
                </Text>
              </Group>
            </>
          )}

          {/* Show login status when not authenticated */}
          {!isAuthenticated && (
            <Group gap="xs">
              <Text c="white" size="sm">
                Please log in to continue
              </Text>
            </Group>
          )}
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        <Stack gap={0} style={{ minHeight: 'calc(100vh - 80px)', width: '100%' }}>
          {/* Content area where different pages will be rendered */}
          <div style={{ flex: 1, padding: 0, width: '100%' }}>
            {/* Show login page when not authenticated */}
            {!isAuthenticated && (
              <LoginPage
                onLogin={(userInfo) => {
                  setLoggedUser(userInfo.userName);
                  setIsAuthenticated(true);
                  setActiveView('welcome');
                  saveAuthState(true, userInfo.userName, 'welcome');
                }}
              />
            )}

            {/* Show protected pages only when authenticated */}
            {isAuthenticated && (
              <>
                {activeView === 'register' && (
                  <RegistrationPage
                    onRegister={(data) => {
                      console.log('Registering student:', data);
                      // Handle registration logic here
                    }}
                  />
                )}
                {activeView === 'detection' && (
                  <DetectionPage
                    // onDetection={(data) => {
                    //   // console.log('Face detected:', data);
                    //   // Handle detection logic here
                    // }}
                  />
                )}
                {activeView === 'welcome' && (
                  <WelcomeScreen
                    onNavigate={(view) => {
                      setActiveView(view);
                      if (loggedUser) {
                        saveAuthState(true, loggedUser, view);
                      }
                    }}
                  />
                )}
                {activeView === 'settings' && (
                  <SettingsPage
                    onSaveSettings={(settings) => {
                      console.log('Saving settings:', settings);
                      // Handle settings save logic here
                    }}
                  />
                )}
              </>
            )}
          </div>
        </Stack>
      </AppShell.Main>
    </AppShell>
  );
}