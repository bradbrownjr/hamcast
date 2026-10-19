import { createTheme } from '@mui/material/styles';

// Green highlight, checked for contrast: #2E7D32 on white is 5.13:1 and
// #66BB6A on MUI's dark background (#121212) is 7.92:1, both above WCAG AA.
export const theme = createTheme({
  cssVariables: { colorSchemeSelector: 'class' },
  colorSchemes: {
    light: { palette: { primary: { main: '#2E7D32' }, secondary: { main: '#00695C' } } },
    dark: { palette: { primary: { main: '#66BB6A' }, secondary: { main: '#4DB6AC' } } },
  },
  shape: { borderRadius: 12 },
});
