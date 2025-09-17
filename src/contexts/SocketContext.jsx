import React, { useEffect, useRef, useState, useCallback } from 'react';
import { io } from 'socket.io-client';
import { SocketContext } from './SocketContext';

export const SocketProvider = ({ children }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState('disconnected');
  const socketRef = useRef(null);
  const eventListenersRef = useRef(new Map());

  // Get the base URL for connections
  const getSocketUrl = useCallback(() => {
    // In development, connect directly to FastAPI backend
    // In production (Docker), connect to current origin (nginx proxy)
    const isDevelopment = window.location.port === '5173';
    return isDevelopment ? 'http://localhost:8000' : window.location.origin;
  }, []);

  // Connect to SocketIO with Promise support
  const connect = useCallback(() => {
    if (socketRef.current?.connected) {
      console.log('🔌 SocketIO already connected');
      return Promise.resolve(socketRef.current);
    }

    console.log('🔌 Connecting to SocketIO...');
    setConnectionState('connecting');

    return new Promise((resolve, reject) => {
      const socket = io(getSocketUrl(), {
        transports: ['polling', 'websocket'],
        forceNew: true,
        timeout: 20000
      });
      socketRef.current = socket;

      socket.on('connect', () => {
        console.log('✅ SocketIO connected');
        setIsConnected(true);
        setConnectionState('connected');
        resolve(socket);
      });

      socket.on('disconnect', () => {
        console.log('❌ SocketIO disconnected');
        setIsConnected(false);
        setConnectionState('disconnected');
      });

      socket.on('connect_error', (error) => {
        console.error('🔌 SocketIO connection error:', error);
        setConnectionState('error');
        reject(error);
      });

      // Timeout fallback
      setTimeout(() => {
        if (!socket.connected) {
          setConnectionState('error');
          reject(new Error('Connection timeout'));
        }
      }, 20000);
    });
  }, [getSocketUrl]);

  // Disconnect from SocketIO
  const disconnect = useCallback(() => {
    if (socketRef.current) {
      console.log('🔌 Disconnecting SocketIO...');
      socketRef.current.disconnect();
      socketRef.current = null;
      setIsConnected(false);
      setConnectionState('disconnected');
      eventListenersRef.current.clear();
    }
  }, []);

  // Add event listener with automatic cleanup
  const on = useCallback((event, handler) => {
    if (!socketRef.current) {
      console.warn(`Cannot add listener for ${event}: SocketIO not connected`);
      return;
    }

    socketRef.current.on(event, handler);

    // Track listeners for cleanup
    if (!eventListenersRef.current.has(event)) {
      eventListenersRef.current.set(event, new Set());
    }
    eventListenersRef.current.get(event).add(handler);

    // Return cleanup function
    return () => {
      if (socketRef.current) {
        socketRef.current.off(event, handler);
      }
      const handlers = eventListenersRef.current.get(event);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          eventListenersRef.current.delete(event);
        }
      }
    };
  }, []);

  // Remove event listener
  const off = useCallback((event, handler) => {
    if (socketRef.current) {
      socketRef.current.off(event, handler);
    }
    const handlers = eventListenersRef.current.get(event);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        eventListenersRef.current.delete(event);
      }
    }
  }, []);

  // Emit event
  const emit = useCallback((event, data) => {
    if (!socketRef.current?.connected) {
      console.warn(`Cannot emit ${event}: SocketIO not connected`);
      return false;
    }
    socketRef.current.emit(event, data);
    return true;
  }, []);

  // Get current socket instance
  const getSocket = useCallback(() => {
    return socketRef.current;
  }, []);

  // Auto-connect on mount, cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  const value = {
    isConnected,
    connectionState,
    connect,
    disconnect,
    on,
    off,
    emit,
    getSocket,
    getSocketUrl,
  };

  return (
    <SocketContext.Provider value={value}>
      {children}
    </SocketContext.Provider>
  );
};