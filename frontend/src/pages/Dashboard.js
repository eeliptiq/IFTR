import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import axios from 'axios';
import { 
  ShoppingBag, Truck, Store, Heart, TrendingUp, 
  Clock, MapPin, ArrowRight, Plus
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const Dashboard = () => {
  const { user, token } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [recentOrders, setRecentOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboardData();
  }, [user]);

  const fetchDashboardData = async () => {
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      
      // Fetch recent orders
      const ordersRes = await axios.get(`${API}/orders`, {
        headers,
        withCredentials: true
      });
      setRecentOrders(ordersRes.data.slice(0, 5));

      // Admin stats
      if (user?.role === 'admin') {
        const statsRes = await axios.get(`${API}/admin/stats`, {
          headers,
          withCredentials: true
        });
        setStats(statsRes.data);
      }
    } catch (error) {
      console.error('Dashboard error:', error);
    } finally {
      setLoading(false);
    }
  };

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  };

  const getRoleContent = () => {
    const role = user?.role || 'customer';

    switch (role) {
      case 'customer':
        return <CustomerDashboard orders={recentOrders} />;
      case 'driver':
        return <DriverDashboard />;
      case 'restaurant':
        return <RestaurantDashboard />;
      case 'organization':
        return <OrganizationDashboard />;
      case 'admin':
        return <AdminDashboard stats={stats} />;
      default:
        return <CustomerDashboard orders={recentOrders} />;
    }
  };

  return (
    <div className="p-6 md:p-8 space-y-8" data-testid="dashboard">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-2"
      >
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
          {getGreeting()}, {user?.name?.split(' ')[0] || 'there'}
        </h1>
        <p className="text-muted-foreground">
          Here's what's happening with your SharePlate account.
        </p>
      </motion.div>

      {/* Role-specific content */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="animate-pulse">
              <CardContent className="p-6">
                <div className="h-20 bg-muted rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        getRoleContent()
      )}
    </div>
  );
};

// Customer Dashboard
const CustomerDashboard = ({ orders }) => {
  const navigate = useNavigate();

  const quickActions = [
    { icon: Store, label: 'Browse Restaurants', to: '/restaurants', color: 'bg-green-500/10 text-green-600' },
    { icon: ShoppingBag, label: 'My Orders', to: '/orders', color: 'bg-blue-500/10 text-blue-600' },
    { icon: Heart, label: 'Donate Food', to: '/donate', color: 'bg-pink-500/10 text-pink-600' },
  ];

  return (
    <div className="space-y-8">
      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {quickActions.map((action, i) => (
          <motion.div
            key={action.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <Card 
              className="cursor-pointer hover:shadow-lg transition-shadow"
              onClick={() => navigate(action.to)}
              data-testid={`quick-action-${action.label.toLowerCase().replace(' ', '-')}`}
            >
              <CardContent className="p-6 flex items-center gap-4">
                <div className={`p-3 rounded-xl ${action.color}`}>
                  <action.icon className="w-6 h-6" />
                </div>
                <div>
                  <p className="font-semibold">{action.label}</p>
                  <p className="text-sm text-muted-foreground">
                    {action.label === 'Browse Restaurants' && 'Find your next meal'}
                    {action.label === 'My Orders' && 'Track your deliveries'}
                    {action.label === 'Donate Food' && 'Help the community'}
                  </p>
                </div>
                <ArrowRight className="w-5 h-5 ml-auto text-muted-foreground" />
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Recent Orders */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Recent Orders</CardTitle>
          <Button variant="ghost" onClick={() => navigate('/orders')}>
            View All
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </CardHeader>
        <CardContent>
          {orders.length === 0 ? (
            <div className="text-center py-8">
              <ShoppingBag className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
              <p className="text-muted-foreground">No orders yet</p>
              <Button className="mt-4" onClick={() => navigate('/restaurants')}>
                Order Now
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              {orders.map((order) => (
                <div key={order.order_id} className="flex items-center justify-between p-4 rounded-lg bg-secondary/50">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                      <ShoppingBag className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                      <p className="font-medium">Order #{order.order_id.slice(-8)}</p>
                      <p className="text-sm text-muted-foreground">{order.items?.length || 0} items</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="font-mono font-semibold">${order.total_amount?.toFixed(2)}</p>
                    <span className={`status-badge ${
                      order.status === 'delivered' ? 'status-completed' :
                      order.status === 'cancelled' ? 'bg-red-100 text-red-800' :
                      'status-pending'
                    }`}>
                      {order.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

// Driver Dashboard
const DriverDashboard = () => {
  const navigate = useNavigate();
  const { token } = useAuth();
  const [earnings, setEarnings] = useState({ total_deliveries: 0, total_earnings: 0, rating: 5.0 });
  const [activeDelivery, setActiveDelivery] = useState(null);

  useEffect(() => {
    fetchDriverData();
  }, []);

  const fetchDriverData = async () => {
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      
      const [earningsRes, activeRes] = await Promise.all([
        axios.get(`${API}/drivers/earnings`, { headers, withCredentials: true }),
        axios.get(`${API}/drivers/active-delivery`, { headers, withCredentials: true })
      ]);
      
      setEarnings(earningsRes.data);
      setActiveDelivery(activeRes.data);
    } catch (error) {
      console.error('Driver data error:', error);
    }
  };

  return (
    <div className="space-y-8">
      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-gradient-to-br from-green-500/10 to-green-600/5">
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Earnings</p>
                <p className="text-3xl font-bold font-mono text-green-600">${earnings.total_earnings.toFixed(2)}</p>
              </div>
              <TrendingUp className="w-8 h-8 text-green-600" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Deliveries</p>
                <p className="text-3xl font-bold font-mono">{earnings.total_deliveries}</p>
              </div>
              <Truck className="w-8 h-8 text-primary" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Rating</p>
                <p className="text-3xl font-bold font-mono">{earnings.rating.toFixed(1)}⭐</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Active Delivery or Available Orders */}
      <Card>
        <CardHeader>
          <CardTitle>{activeDelivery ? 'Active Delivery' : 'Available Orders'}</CardTitle>
        </CardHeader>
        <CardContent>
          {activeDelivery ? (
            <div className="p-4 rounded-lg bg-primary/10 border border-primary/20">
              <p className="font-semibold">Order #{activeDelivery.order_id.slice(-8)}</p>
              <p className="text-sm text-muted-foreground mt-1">In Progress</p>
              <Button className="mt-4" onClick={() => navigate('/driver/deliveries')}>
                View Details
              </Button>
            </div>
          ) : (
            <div className="text-center py-8">
              <Truck className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
              <p className="text-muted-foreground">No active deliveries</p>
              <Button className="mt-4" onClick={() => navigate('/driver/deliveries')}>
                Find Orders
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

// Restaurant Dashboard
const RestaurantDashboard = () => {
  const navigate = useNavigate();

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="cursor-pointer hover:shadow-lg transition-shadow" onClick={() => navigate('/restaurant/menu')}>
          <CardContent className="p-6 flex items-center gap-4">
            <div className="p-3 rounded-xl bg-orange-500/10 text-orange-600">
              <Store className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold">Manage Menu</p>
              <p className="text-sm text-muted-foreground">Add or update items</p>
            </div>
          </CardContent>
        </Card>
        <Card className="cursor-pointer hover:shadow-lg transition-shadow" onClick={() => navigate('/restaurant/orders')}>
          <CardContent className="p-6 flex items-center gap-4">
            <div className="p-3 rounded-xl bg-blue-500/10 text-blue-600">
              <ShoppingBag className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold">View Orders</p>
              <p className="text-sm text-muted-foreground">Manage incoming orders</p>
            </div>
          </CardContent>
        </Card>
        <Card className="cursor-pointer hover:shadow-lg transition-shadow" onClick={() => navigate('/restaurant/surplus')}>
          <CardContent className="p-6 flex items-center gap-4">
            <div className="p-3 rounded-xl bg-pink-500/10 text-pink-600">
              <Heart className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold">Surplus Food</p>
              <p className="text-sm text-muted-foreground">List excess food for donation</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

// Organization Dashboard
const OrganizationDashboard = () => {
  const navigate = useNavigate();

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="cursor-pointer hover:shadow-lg transition-shadow" onClick={() => navigate('/organization/requests')}>
          <CardContent className="p-6 flex items-center gap-4">
            <div className="p-3 rounded-xl bg-purple-500/10 text-purple-600">
              <Heart className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold">Available Food</p>
              <p className="text-sm text-muted-foreground">Browse surplus food listings</p>
            </div>
          </CardContent>
        </Card>
        <Card className="cursor-pointer hover:shadow-lg transition-shadow" onClick={() => navigate('/organization/received')}>
          <CardContent className="p-6 flex items-center gap-4">
            <div className="p-3 rounded-xl bg-green-500/10 text-green-600">
              <ShoppingBag className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold">Received Food</p>
              <p className="text-sm text-muted-foreground">View your food donations</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

// Admin Dashboard
const AdminDashboard = ({ stats }) => {
  const navigate = useNavigate();

  if (!stats) return null;

  const statCards = [
    { label: 'Total Orders', value: stats.total_orders, icon: ShoppingBag, color: 'text-blue-600' },
    { label: 'Active Orders', value: stats.active_orders, icon: Clock, color: 'text-orange-600' },
    // Money Stripe confirmed, not the value of what was delivered: the impact
    // page reports delivered value, which includes orders nobody paid for.
    { label: 'Revenue Collected', value: `$${(stats.total_revenue || 0).toFixed(2)}`, icon: TrendingUp, color: 'text-green-600' },
    { label: 'Meals Donated', value: stats.meals_donated, icon: Heart, color: 'text-pink-600' },
    { label: 'Active Drivers', value: stats.active_drivers, icon: Truck, color: 'text-purple-600' },
    { label: 'Restaurants', value: stats.active_restaurants, icon: Store, color: 'text-amber-600' },
  ];

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {statCards.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
          >
            <Card>
              <CardContent className="p-4">
                <stat.icon className={`w-6 h-6 ${stat.color} mb-2`} />
                <p className="text-2xl font-bold font-mono">{stat.value}</p>
                <p className="text-xs text-muted-foreground">{stat.label}</p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <Card className="cursor-pointer" onClick={() => navigate('/admin/users')}>
          <CardHeader>
            <CardTitle>User Management</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">View and manage all platform users</p>
          </CardContent>
        </Card>
        <Card className="cursor-pointer" onClick={() => navigate('/admin/routing')}>
          <CardHeader>
            <CardTitle>Routing Analytics</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">View routing optimization metrics</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Dashboard;
