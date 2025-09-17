import { MantineProvider } from '@mantine/core';
import { MainAppShell } from './components/AppShell';
import { SocketProvider } from './contexts/SocketContext.jsx';
import { theme } from './theme';
import '@mantine/core/styles.css';

function App() {
  return (
    <MantineProvider theme={theme}>
      <SocketProvider>
        <MainAppShell />
      </SocketProvider>
    </MantineProvider>
  );
}

export default App
