import { createTheme, type MantineColorsTuple } from '@mantine/core';

// Own neutral fintech palette: a warm red accent, not a brand identity of any bank.
const brand: MantineColorsTuple = [
  '#fff0f0',
  '#ffdede',
  '#ffbcbd',
  '#fb9597',
  '#f46b6e',
  '#ea4549',
  '#d6282e',
  '#b71d23',
  '#93161b',
  '#6e0f13',
];

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: 6,
  colors: { brand },
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  headings: {
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
    fontWeight: '700',
  },
  defaultRadius: 'md',
  cursorType: 'pointer',
  focusRing: 'auto',
  components: {
    Button: { defaultProps: { radius: 'md' } },
    Modal: { defaultProps: { radius: 'lg', overlayProps: { backgroundOpacity: 0.45, blur: 2 } } },
    Tooltip: { defaultProps: { withArrow: true } },
  },
});
