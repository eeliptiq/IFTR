import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'sonner';

const AuthContext = createContext(null);

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// The sign-up UI speaks in friendly role names; the backend uses the
// canonical UserRole values. Map between the two.
const ROLE_MAP = {
  customer: 'customer',
  driver: 'driver',
  restaurant: 'restaurant_admin',
  organization: 'organization_admin',
};

// ...and back again, so the existing role-based UI keeps working unchanged.
const ROLE_UI = {
  restaurant_admin: 'restaurant',
  organization_admin: 'organization',
};

const normalizeUser = (u) => (u ? { ...u, role: ROLE_UI[u.role] || u.role } : u);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState(localStorage.getItem('token'));

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`, {
        withCredentials: true,
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      const account = normalizeUser(response.data);
      setUser(account);
      return account;
    } catch (error) {
      setUser(null);
      localStorage.removeItem('token');
      setToken(null);
      return null;
    } finally {
      setLoading(false);
    }
  };

  const login = async (email, password) => {
    const response = await axios.post(`${API}/auth/login`, { email, password }, {
      withCredentials: true
    });
    const { user: userData, access_token: newToken } = response.data;
    setUser(normalizeUser(userData));
    setToken(newToken);
    localStorage.setItem('token', newToken);
    return userData;
  };

  const register = async (userData) => {
    const payload = {
      ...userData,
      role: ROLE_MAP[userData.role] || userData.role,
    };
    const response = await axios.post(`${API}/auth/register`, payload, {
      withCredentials: true
    });
    const { user: newUser, access_token: newToken } = response.data;
    setUser(normalizeUser(newUser));
    setToken(newToken);
    localStorage.setItem('token', newToken);
    return newUser;
  };

  const processOAuthSession = async (sessionId) => {
    const response = await axios.post(`${API}/auth/session`, 
      { session_id: sessionId },
      { withCredentials: true }
    );
    const { user: userData, token: newToken } = response.data;
    setUser(normalizeUser(userData));
    setToken(newToken);
    localStorage.setItem('token', newToken);
    return userData;
  };

  const logout = async () => {
    try {
      await axios.post(`${API}/auth/logout`, {}, {
        withCredentials: true,
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
    } catch (error) {
      console.error('Logout error:', error);
    }
    setUser(null);
    setToken(null);
    localStorage.removeItem('token');
  };

  const updateProfile = async (profileData) => {
    const response = await axios.put(`${API}/users/me`, profileData, {
      withCredentials: true,
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    setUser(normalizeUser(response.data));
    return response.data;
  };

  const initiateGoogleLogin = () => {
    // Google OAuth used to be brokered by the Emergent platform. It is not
    // wired to this self-hosted backend yet, so fail softly instead of
    // bouncing the user to a dead redirect.
    toast.error('Google sign-in is not available yet — please use email and password.');
  };

  const value = {
    user,
    loading,
    token,
    login,
    register,
    logout,
    updateProfile,
    checkAuth,
    processOAuthSession,
    initiateGoogleLogin,
    isAuthenticated: !!user
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export default AuthContext;
