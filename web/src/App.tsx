import { useEffect, useState } from 'react';
import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import IconButton from '@mui/material/IconButton';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Toolbar from '@mui/material/Toolbar';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { useColorScheme } from '@mui/material/styles';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import SettingsBrightnessIcon from '@mui/icons-material/SettingsBrightness';
import PodcastsIcon from '@mui/icons-material/Podcasts';
import Listen from './pages/Listen';
import Manage from './pages/Manage';

type Page = 'listen' | 'manage';

function pageFromPath(): Page {
  return location.pathname.startsWith('/manage') ? 'manage' : 'listen';
}

// ========== THEME TOGGLE ==========
// Cycles system -> light -> dark. MUI keeps the choice in localStorage.
const NEXT = { system: 'light', light: 'dark', dark: 'system' } as const;
const LABEL = { system: 'Theme: follow system', light: 'Theme: light', dark: 'Theme: dark' };

function ThemeToggle() {
  const { mode, setMode } = useColorScheme();
  if (!mode) return null;
  const icon = mode === 'light' ? <LightModeIcon /> : mode === 'dark' ? <DarkModeIcon /> : <SettingsBrightnessIcon />;
  return (
    <Tooltip title={LABEL[mode]}>
      <IconButton color="inherit" aria-label={LABEL[mode]} onClick={() => setMode(NEXT[mode])}>
        {icon}
      </IconButton>
    </Tooltip>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromPath);

  useEffect(() => {
    const onPop = () => setPage(pageFromPath());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const go = (p: Page) => {
    history.pushState(null, '', p === 'manage' ? '/manage' : '/');
    setPage(p);
  };

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      {/* Green bar in light mode; a dark surface with green accents in dark mode */}
      <AppBar
        position="sticky"
        color="primary"
        sx={(t) => t.applyStyles('dark', { bgcolor: 'background.paper', color: 'text.primary' })}
      >
        <Toolbar>
          <PodcastsIcon sx={(t) => ({ mr: 1, ...t.applyStyles('dark', { color: 'primary.main' }) })} />
          <Typography variant="h6" component="h1" sx={{ flexGrow: 1 }}>
            hamcast
          </Typography>
          <ThemeToggle />
        </Toolbar>
        <Tabs
          value={page}
          onChange={(_, v: Page) => go(v)}
          textColor="inherit"
          variant="scrollable"
          scrollButtons={false}
          sx={(t) => ({
            px: { xs: 0, sm: 2 },
            '& .MuiTab-root': { minWidth: { xs: 90, sm: 120 } },
            '& .MuiTabs-indicator': { bgcolor: 'primary.contrastText', height: 3 },
            ...t.applyStyles('dark', {
              '& .Mui-selected': { color: 'primary.main' },
              '& .MuiTabs-indicator': { bgcolor: 'primary.main' },
            }),
          })}
        >
          <Tab value="listen" label="Listen" />
          <Tab value="manage" label="Manage" />
        </Tabs>
      </AppBar>
      {/* Listen is wider so 4 nets fit across a 1080p screen */}
      <Container maxWidth={page === 'listen' ? 'xl' : 'lg'} sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        {page === 'listen' ? <Listen /> : <Manage />}
      </Container>
    </Box>
  );
}
