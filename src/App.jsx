import { MantineProvider } from '@mantine/core';
import { MainAppShell } from './components/AppShell';
import { theme } from './theme';
import '@mantine/core/styles.css';

function App() {
  return (
    <MantineProvider theme={theme}>
      <MainAppShell />
    </MantineProvider>
  );
}

export default App
