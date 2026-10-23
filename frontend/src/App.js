import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Toaster } from './components/ui/sonner';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';

// Pages
import Landing from './pages/Landing';
import Auth from './pages/Auth';
import AuthCallback from './pages/AuthCallback';
import Dashboard from './pages/Dashboard';
import Restaurants from './pages/Restaurants';
import RestaurantDetail from './pages/RestaurantDetail';
import Orders from './pages/Orders';
import OrderTracking from './pages/OrderTracking';
import Settings from './pages/Settings';
import Support from './pages/Support';
import { PaymentSuccess, PaymentCancel } from './pages/Payment';
import CryptoPayment from './pages/CryptoPayment';
import DriverDeliveries from './pages/DriverDeliveries';
import DriverRouting from './pages/DriverRouting';
import RestaurantMenu from './pages/RestaurantMenu';
import RestaurantSurplus from './pages/RestaurantSurplus';
import RestaurantOrders from './pages/RestaurantOrders';
import { OrganizationRequests, OrganizationReceived } from './pages/OrganizationPages';
import RegisterOrganization from './pages/RegisterOrganization';
import CommunityImpact from './pages/CommunityImpact';
import RegisterRestaurant from './pages/RegisterRestaurant';
import DriverEarnings from './pages/DriverEarnings';
import AdminUsers from './pages/AdminUsers';

// Layout
import DashboardLayout from './components/layout/DashboardLayout';

import './App.css';

// Protected Route Component
const ProtectedRoute = ({ children }) => {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/auth" state={{ from: location }} replace />;
  }

  return children;
};

// App Router with Auth Check
const AppRouter = () => {
  const location = useLocation();
  
  // Handle OAuth callback - check for session_id in hash BEFORE rendering routes
  if (location.hash?.includes('session_id=')) {
    return <AuthCallback />;
  }

  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<Landing />} />
      <Route path="/auth" element={<Auth />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      
      {/* Payment Routes (semi-public, need auth for status check) */}
      <Route path="/payment/success" element={<PaymentSuccess />} />
      <Route path="/payment/cancel" element={<PaymentCancel />} />
      {/* Crypto needs the signed-in customer for its invoice and status calls,
          but not the dashboard chrome: it is a payment page, not a section. */}
      <Route
        path="/payment/crypto/:orderId"
        element={
          <ProtectedRoute>
            <CryptoPayment />
          </ProtectedRoute>
        }
      />

      {/* Protected Routes with Dashboard Layout */}
      <Route
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/restaurants" element={<Restaurants />} />
        <Route path="/restaurants/:restaurantId" element={<RestaurantDetail />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/orders/:orderId" element={<OrderTracking />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/support" element={<Support />} />
        <Route path="/donate" element={<Donate />} />
        
        {/* Driver Routes */}
        <Route path="/driver/deliveries" element={<DriverDeliveries />} />
        <Route path="/driver/earnings" element={<DriverEarnings />} />
        <Route path="/driver/routing" element={<DriverRouting />} />
        
        {/* Restaurant Routes */}
        <Route path="/restaurant/register" element={<RegisterRestaurant />} />
        <Route path="/restaurant/menu" element={<RestaurantMenu />} />
        <Route path="/restaurant/orders" element={<RestaurantOrders />} />
        <Route path="/restaurant/surplus" element={<RestaurantSurplus />} />
        
        {/* Organization Routes */}
        <Route path="/organization/register" element={<RegisterOrganization />} />
        <Route path="/organization/requests" element={<OrganizationRequests />} />
        <Route path="/organization/received" element={<OrganizationReceived />} />
        
        {/* Community */}
        <Route path="/impact" element={<CommunityImpact />} />
        
        {/* Admin Routes */}
        <Route path="/admin/analytics" element={<AdminAnalytics />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/routing" element={<AdminRouting />} />
      </Route>

      {/* Catch all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

// Placeholder components for remaining routes
const Donate = () => <PlaceholderPage title="Donate Food" description="Help feed the community by donating meals" />;
const AdminAnalytics = () => <PlaceholderPage title="Analytics Dashboard" description="Platform-wide analytics" />;
const AdminRouting = () => <PlaceholderPage title="Routing Metrics" description="View routing optimization data" />;

const PlaceholderPage = ({ title, description }) => (
  <div className="p-6 md:p-8">
    <h1 className="text-3xl font-bold tracking-tight mb-2">{title}</h1>
    <p className="text-muted-foreground mb-8">{description}</p>
    <div className="flex items-center justify-center h-64 bg-secondary/30 rounded-2xl border-2 border-dashed border-border">
      <p className="text-muted-foreground">Coming soon...</p>
    </div>
  </div>
);

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppRouter />
          <Toaster position="top-right" richColors />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
