import { useState } from 'react';
import {
  Paper,
  Stack,
  Title,
  TextInput,
  PasswordInput,
  Button,
  Group,
  Image,
  Box,
  Alert,
} from '@mantine/core';
import { IconUser, IconLock, IconAlertCircle } from '@tabler/icons-react';
import apiService from '../services/api';

export function LoginPage({ onLogin }) {
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async () => {
    if (!loginId || !password) {
      setError('Please enter both login ID and password');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const result = await apiService.login(loginId, password);

      if (result.success) {
        onLogin({
          userId: result.admin_id,
          userName: result.admin_name,
          isAuthenticated: true
        });
      } else {
        setError(result.message || 'Login failed');
      }
    } catch (error) {
      setError('Connection error. Please check if the server is running.');
      console.error('Login error:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box style={{ width: '100%', minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Stack gap="xl" style={{ maxWidth: '400px' }}>
        {/* Header with Logo/Title */}
        <Box ta="center" mb="md">
          <Title order={2} c="rgb(0, 36, 61)" mb="xs">
            Face Recognition System
          </Title>
        </Box>

        {/* Login Form */}
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
              Login
            </Title>

            <TextInput
              leftSection={<IconUser size={16} />}
              label="Login ID"
              placeholder="Enter your login ID"
              value={loginId}
              onChange={(event) => setLoginId(event.currentTarget.value)}
              styles={{
                input: {
                  borderColor: 'rgb(0, 36, 61)',
                  '&:focus': {
                    borderColor: 'rgb(0, 170, 127)',
                  },
                },
              }}
            />

            <PasswordInput
              leftSection={<IconLock size={16} />}
              label="Password"
              placeholder="Enter your password"
              value={password}
              onChange={(event) => setPassword(event.currentTarget.value)}
              styles={{
                input: {
                  borderColor: 'rgb(0, 36, 61)',
                  '&:focus': {
                    borderColor: 'rgb(0, 170, 127)',
                  },
                },
              }}
            />

            {error && (
              <Alert
                icon={<IconAlertCircle size={16} />}
                color="red"
                title="Login Error"
              >
                {error}
              </Alert>
            )}

            <Button
              onClick={handleLogin}
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
              disabled={!loginId || !password || loading}
            >
              {loading ? 'Logging in...' : 'Login'}
            </Button>
          </Stack>
        </Paper>
      </Stack>
    </Box>
  );
}