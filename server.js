import express from 'express';
import cors from 'cors';
import { createProxyMiddleware } from 'http-proxy-middleware';
import multer from 'multer';
import http from 'http';

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors({
  origin: ['http://localhost:3000', 'http://localhost:5173', 'http://localhost:5174'],
  credentials: true
}));

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// Multer configuration for file uploads
const storage = multer.memoryStorage();
const upload = multer({
  storage: storage,
  limits: {
    fileSize: 10 * 1024 * 1024 // 10MB limit
  }
});

// Proxy middleware for FastAPI backend
const apiProxy = createProxyMiddleware({
  target: process.env.API_BASE_URL || 'http://localhost:8000',
  changeOrigin: true,
  // Remove the pathRewrite that was incorrectly prepending /api/
  onError: (err, req, res) => {
    console.error('Proxy Error:', err.message);
    res.status(500).json({
      success: false,
      message: 'Backend service unavailable',
      error: err.message
    });
  },
  onProxyReq: (proxyReq, req) => {
    console.log(`📡 Proxying ${req.method} ${req.url} to FastAPI backend`);
  }
});

// Apply proxy middleware to all /api routes
app.use('/api', apiProxy);

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'Express Proxy Server',
    timestamp: new Date().toISOString(),
    uptime: process.uptime()
  });
});

// File upload endpoint with processing
app.post('/api/upload/face-image', upload.single('image'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({
        success: false,
        message: 'No image file provided'
      });
    }

    // Convert buffer to base64
    const base64Image = req.file.buffer.toString('base64');
    const mimeType = req.file.mimetype;
    const imageData = `data:${mimeType};base64,${base64Image}`;

    // Forward to Python backend for processing
    const response = await fetch(`${process.env.API_BASE_URL || 'http://localhost:8000'}/api/recognition/detect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        image_data: imageData
      })
    });

    const result = await response.json();
    res.json(result);

  } catch (error) {
    console.error('Image upload error:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to process image',
      error: error.message
    });
  }
});

// WebSocket support for real-time face detection (future enhancement)
const server = http.createServer(app);

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('🛑 Received SIGTERM, shutting down gracefully');
  server.close(() => {
    console.log('✅ Express server closed');
    process.exit(0);
  });
});

process.on('SIGINT', () => {
  console.log('🛑 Received SIGINT, shutting down gracefully');
  server.close(() => {
    console.log('✅ Express server closed');
    process.exit(0);
  });
});

// Start server
server.listen(PORT, () => {
  console.log('🚀 Express Proxy Server starting...');
  console.log(`📡 Server running on http://localhost:${PORT}`);
  console.log(`🔄 Proxying /api/* requests to FastAPI backend (${process.env.API_BASE_URL || 'http://localhost:8000'})`);
  console.log('📁 File upload endpoint: POST /api/upload/face-image');
  console.log('💓 Health check: GET /health');
  console.log('🎯 CORS enabled for React frontend');
});

export default app;