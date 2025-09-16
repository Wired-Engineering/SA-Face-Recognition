import { createTheme } from '@mantine/core';

export const theme = createTheme({
  colors: {
    // Primary color palette based on your specifications
    signature: [
      '#f0f4f8',  // lightest shade - much lighter for better contrast
      '#e1ebff',  // lighter background
      '#b8d0e8',  // light
      '#849ca4',  // your specified color - medium
      '#4c5c68',  // your specified color - medium-dark
      '#28385c',  // your specified color - dark
      '#132443',  // your darkest specified color
      '#0f1e35',  // darker
      '#0a1628',  // darkest
      '#041016',  // ultra dark
    ],
    // Secondary palette for accents
    accent: [
      '#ffffff',  // pure white for backgrounds
      '#f8fafc',  // very light gray
      '#e1ebff',  // light blue background
      '#d1dff7',  // slightly darker blue
      '#849ca4',  // medium tone
      '#4c5c68',  // medium-dark
      '#28385c',  // dark
      '#132443',  // darkest
      '#0f1e35',  // very dark
      '#041016',  // ultra dark
    ],
  },
  primaryColor: 'signature',
  primaryShade: 5, // Use #28385c as the primary shade

  components: {
    AppShell: {
      styles: {
        main: {
          backgroundColor: 'var(--mantine-color-accent-2)', // darker background #e1ebff
        },
        header: {
          backgroundColor: 'var(--mantine-color-signature-6)', // #132443
          borderColor: 'var(--mantine-color-white)',
          borderWidth: '2px',
          borderRadius: '15px',
        },
      },
    },
    Button: {
      styles: (theme, params) => ({
        root: {
          borderRadius: '8px',
          fontFamily: 'Tahoma, sans-serif',
          fontWeight: 'bold',
          fontSize: '10pt',
          minHeight: '40px',
          // Strong contrast for signature color buttons
          ...(params.color === 'signature' && {
            backgroundColor: 'var(--mantine-color-signature-6)', // #132443
            color: 'white',
            border: '2px solid var(--mantine-color-signature-6)',
            '&:hover': {
              backgroundColor: 'var(--mantine-color-signature-5)', // #28385c
              borderColor: 'var(--mantine-color-signature-5)',
              transform: 'translateY(-1px)',
            },
            '&:disabled': {
              backgroundColor: 'var(--mantine-color-gray-3)',
              color: 'var(--mantine-color-gray-6)',
              borderColor: 'var(--mantine-color-gray-3)',
            },
          }),
          // Strong outline variant styling
          ...(params.variant === 'outline' && params.color === 'signature' && {
            backgroundColor: 'white',
            borderColor: 'var(--mantine-color-signature-6)',
            color: 'var(--mantine-color-signature-6)',
            borderWidth: '2px',
            '&:hover': {
              backgroundColor: 'var(--mantine-color-signature-6)',
              color: 'white',
              transform: 'translateY(-1px)',
            },
          }),
          // Subtle variant for header buttons
          ...(params.variant === 'subtle' && {
            color: 'white',
            backgroundColor: 'rgba(255, 255, 255, 0.1)',
            backdropFilter: 'blur(8px)',
            border: '1px solid rgba(255, 255, 255, 0.2)',
            '&:hover': {
              backgroundColor: 'rgba(255, 255, 255, 0.25)',
              color: 'white',
              transform: 'translateY(-1px)',
            },
          }),
        },
      }),
    },
    TextInput: {
      styles: {
        input: {
          backgroundColor: 'white',
          borderColor: 'var(--mantine-color-signature-4)',
          borderWidth: '2px',
          color: '#000000', // True black text
          '&:focus': {
            borderColor: 'var(--mantine-color-signature-6)',
            backgroundColor: 'var(--mantine-color-accent-1)',
          },
        },
        label: {
          color: '#000000', // True black text for labels
          fontWeight: 'bold',
        },
      },
    },
    PasswordInput: {
      styles: {
        input: {
          backgroundColor: 'white',
          borderColor: 'var(--mantine-color-signature-4)',
          borderWidth: '2px',
          color: '#000000', // True black text
          '&:focus': {
            borderColor: 'var(--mantine-color-signature-6)',
            backgroundColor: 'var(--mantine-color-accent-1)',
          },
        },
        label: {
          color: '#000000', // True black text for labels
          fontWeight: 'bold',
        },
      },
    },
    NumberInput: {
      styles: {
        input: {
          backgroundColor: 'white',
          borderColor: 'var(--mantine-color-signature-4)',
          borderWidth: '2px',
          color: '#000000', // True black text
          '&:focus': {
            borderColor: 'var(--mantine-color-signature-6)',
            backgroundColor: 'var(--mantine-color-accent-1)',
          },
        },
        label: {
          color: '#000000', // True black text for labels
          fontWeight: 'bold',
        },
      },
    },
    Select: {
      styles: {
        input: {
          backgroundColor: 'white',
          borderColor: 'var(--mantine-color-signature-4)',
          borderWidth: '2px',
          color: '#000000', // True black text
          '&:focus': {
            borderColor: 'var(--mantine-color-signature-6)',
            backgroundColor: 'var(--mantine-color-accent-1)',
          },
        },
        label: {
          color: '#000000', // True black text for labels
          fontWeight: 'bold',
        },
        dropdown: {
          borderColor: 'var(--mantine-color-signature-5)',
          borderWidth: '2px',
        },
      },
    },
    Paper: {
      styles: {
        root: {
          backgroundColor: 'white',
          borderColor: 'var(--mantine-color-signature-6)',
          borderWidth: '2px',
          boxShadow: '0 4px 12px rgba(19, 36, 67, 0.15)',
        },
      },
    },
    Card: {
      styles: {
        root: {
          backgroundColor: 'white',
          borderColor: 'var(--mantine-color-signature-5)',
          borderWidth: '2px',
          boxShadow: '0 4px 16px rgba(19, 36, 67, 0.15)',
          '& .mantine-Card-section': {
            borderColor: 'var(--mantine-color-signature-3)',
          },
        },
      },
    },
    Tabs: {
      styles: {
        root: {
          '& .mantine-Tabs-list': {
            backgroundColor: 'white',
            borderRadius: '8px',
            padding: '4px',
            boxShadow: '0 2px 8px rgba(19, 36, 67, 0.1)',
          },
          '& .mantine-Tabs-tab': {
            borderRadius: '6px',
            fontWeight: 'bold',
            color: '#000000', // True black text for tabs
            '&[data-active]': {
              backgroundColor: 'var(--mantine-color-signature-6)',
              color: 'white',
            },
            '&:hover': {
              backgroundColor: 'var(--mantine-color-signature-1)',
              color: '#000000', // Keep black text on hover
            },
          },
        },
        tab: {
          color: '#000000', // Ensure tab text is black
          fontWeight: 'bold',
          '&[data-active]': {
            color: 'white',
          },
        },
      },
    },
    Title: {
      styles: {
        root: {
          fontFamily: 'Sitka, serif',
          color: '#000000', // True black text
        },
      },
    },
    Text: {
      styles: {
        root: {
          color: '#000000', // True black text
        },
      },
    },
    Alert: {
      styles: (theme, params) => ({
        root: {
          borderWidth: '3px',
          fontWeight: '500',
          borderRadius: '8px',
          padding: '16px',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
          // Ensure proper contrast for different alert colors
          ...(params.color === 'orange' && {
            backgroundColor: '#fff4e6',
            borderColor: '#fd7e14',
            color: '#000000', // Black text for orange alerts
          }),
          ...(params.color === 'yellow' && {
            backgroundColor: '#fff9db',
            borderColor: '#ffd43b',
            color: '#000000', // Black text for yellow alerts
          }),
          ...(params.color === 'green' && {
            backgroundColor: '#ebfbee',
            borderColor: '#51cf66',
            color: '#000000', // Black text for green alerts
          }),
          ...(params.color === 'red' && {
            backgroundColor: '#ffe0e6',
            borderColor: '#ff6b6b',
            color: '#000000', // Black text for red alerts
          }),
          // Default fallback for other colors
          ...(!['orange', 'yellow', 'green', 'red'].includes(params.color) && {
            backgroundColor: 'white',
            borderColor: 'var(--mantine-color-signature-5)',
            color: '#000000', // True black text
          }),
        },
        title: {
          fontWeight: 'bold',
          fontSize: '15px',
          marginBottom: '4px',
        },
        message: {
          fontSize: '14px',
          lineHeight: '1.5',
          fontWeight: '500',
          color: '#000000', // Black message text
        },
        icon: {
          marginRight: '12px',
        },
      }),
    },
    Divider: {
      styles: {
        root: {
          borderColor: 'var(--mantine-color-signature-3)',
          borderWidth: '1px',
        },
      },
    },
  },

  fontFamily: 'Tahoma, sans-serif',
  fontFamilyMonospace: 'Monaco, Courier, monospace',
  headings: {
    fontFamily: 'Sitka, serif',
  },

  other: {
    // Custom theme values for specific use cases
    signatureNavy: '#132443',
    signatureBlue: '#28385c',
    signatureGray: '#4c5c68',
    signatureLightGray: '#849ca4',
    signatureAccent: '#2c4444',
    signatureBackground: '#e1ebff', // light blue background for app
    cardBackground: '#ffffff', // white background for cards
    textDark: '#0f1e35', // very dark text for good contrast
  },
});