import { useState, useEffect } from 'react';
import {
  AppShell,
  Group,
  Title,
  Button,
  Text,
  Stack,
  useMantineTheme,
} from '@mantine/core';
import {
  IconVideo,
  IconUserPlus,
  IconSettings,
  IconLogout,
  IconUser,
} from '@tabler/icons-react';
import { LoginPage } from './LoginPage';
import { RegistrationPage } from './RegistrationPage';
import { SettingsPage } from './SettingsPage';
import { DetectionPage } from './DetectionPage';

export function MainAppShell() {
  const theme = useMantineTheme();
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
          setActiveView(view || 'detection');
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
          backgroundColor: theme.other.signatureBackground,
          minHeight: '100vh',
          padding: 0,
          width: '100vw',
        },
        header: {
          backgroundColor: theme.other.signatureNavy,
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
                      setActiveView(btn.id);
                      if (loggedUser) {
                        saveAuthState(true, loggedUser, btn.id);
                      }
                    }}
                    styles={{
                      root: {
                        color: 'white',
                        backgroundColor: 'transparent',
                        border: 'none',
                        borderRadius: '15px',
                        minHeight: '45px',
                        maxHeight: '50px',
                        fontSize: '10pt',
                        fontFamily: theme.fontFamily,
                        fontWeight: 'bold',
                        paddingLeft: '5px',
                        paddingRight: '5px',
                        '&:hover': {
                          backgroundColor: 'rgba(255, 255, 255, 0.8)',
                          color: theme.other.signatureNavy,
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
                      backgroundColor: 'transparent',
                      border: 'none',
                      borderRadius: '15px',
                      minHeight: '45px',
                      maxHeight: '50px',
                      fontSize: '10pt',
                      fontFamily: theme.fontFamily,
                      fontWeight: 'bold',
                      paddingLeft: '5px',
                      paddingRight: '5px',
                      '&:hover': {
                        backgroundColor: 'rgba(255, 255, 255, 0.8)',
                        color: theme.other.signatureNavy,
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
                  setActiveView('detection');
                  saveAuthState(true, userInfo.userName, 'detection');
                }}
              />
            )}

            {/* Show protected pages only when authenticated */}
            {isAuthenticated && (
              <>
                {activeView === 'register' && (
                  <RegistrationPage
                    onRegister={(data) => {
                      console.log('Registering person:', data);
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