import { MantineProvider } from '@mantine/core';
import { MainAppShell } from './components/AppShell';
import '@mantine/core/styles.css';

function App() {
  return (
    <MantineProvider>
      <MainAppShell />
    </MantineProvider>
  );
}

export default App
