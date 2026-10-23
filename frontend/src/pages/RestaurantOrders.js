import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  ShoppingBag, Clock, CheckCircle, ChefHat, Truck, 
  XCircle, RefreshCw, Package
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RestaurantOrders = () => {
  const { token, user } = useAuth();
  const [restaurant, setRestaurant] = useState(null);
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('pending');

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [activeTab]);

  const fetchData = async () => {
    try {
      const headers = { Authorization: `Bearer ${token}` };
      
      // Get restaurant
      const restRes = await axios.get(`${API}/restaurants`, { headers, withCredentials: true });
      const myRestaurant = restRes.data.find(r => r.user_id === user?.user_id);
      setRestaurant(myRestaurant);
      
      if (myRestaurant) {
        const statusParam = activeTab !== 'all' ? `?status=${activeTab}` : '';
        const ordersRes = await axios.get(
          `${API}/restaurants/${myRestaurant.restaurant_id}/orders${statusParam}`,
          { headers, withCredentials: true }
        );
        setOrders(ordersRes.data);
      }
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateStatus = async (orderId, newStatus) => {
    try {
      await axios.put(`${API}/orders/${orderId}/status?status=${newStatus}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success(`Order ${newStatus.replace('_', ' ')}`);
      fetchData();
    } catch (error) {
      toast.error('Failed to update order');
    }
  };

  const getStatusBadge = (status) => {
    const styles = {
      pending: 'bg-amber-100 text-amber-800',
      confirmed: 'bg-blue-100 text-blue-800',
      preparing: 'bg-purple-100 text-purple-800',
      ready: 'bg-green-100 text-green-800',
      picked_up: 'bg-cyan-100 text-cyan-800',
      in_transit: 'bg-indigo-100 text-indigo-800',
      delivered: 'bg-green-100 text-green-800',
      cancelled: 'bg-red-100 text-red-800'
    };
    return styles[status] || 'bg-gray-100 text-gray-800';
  };

  const getNextAction = (status) => {
    switch (status) {
      case 'pending':
        return { label: 'Confirm', next: 'confirmed', icon: CheckCircle };
      case 'confirmed':
        return { label: 'Start Preparing', next: 'preparing', icon: ChefHat };
      case 'preparing':
        return { label: 'Mark Ready', next: 'ready', icon: Package };
      default:
        return null;
    }
  };

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <div className="animate-pulse space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-32 bg-muted rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (!restaurant) {
    return (
      <div className="p-6 md:p-8">
        <Card>
          <CardContent className="p-12 text-center">
            <ShoppingBag className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">Register a restaurant first</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Count orders by status
  const pendingCount = orders.filter(o => o.status === 'pending').length;
  const activeCount = orders.filter(o => ['confirmed', 'preparing'].includes(o.status)).length;

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="restaurant-orders-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Incoming Orders</h1>
          <p className="text-muted-foreground">{restaurant.name}</p>
        </div>
        <Button variant="outline" size="icon" onClick={fetchData}>
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className={pendingCount > 0 ? 'border-amber-500/50 bg-amber-500/5' : ''}>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-amber-600">{pendingCount}</p>
            <p className="text-sm text-muted-foreground">Pending</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-purple-600">{activeCount}</p>
            <p className="text-sm text-muted-foreground">In Progress</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-green-600">
              {orders.filter(o => o.status === 'ready').length}
            </p>
            <p className="text-sm text-muted-foreground">Ready</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold">
              {orders.filter(o => o.status === 'delivered').length}
            </p>
            <p className="text-sm text-muted-foreground">Delivered Today</p>
          </CardContent>
        </Card>
      </div>

      {/* Orders Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="pending" className="relative">
            Pending
            {pendingCount > 0 && (
              <span className="ml-2 w-5 h-5 rounded-full bg-amber-500 text-white text-xs flex items-center justify-center">
                {pendingCount}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="confirmed">Confirmed</TabsTrigger>
          <TabsTrigger value="preparing">Preparing</TabsTrigger>
          <TabsTrigger value="ready">Ready</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} className="mt-6">
          {orders.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center">
                <ShoppingBag className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-muted-foreground">No orders in this category</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {orders.map((order, i) => {
                const nextAction = getNextAction(order.status);
                
                return (
                  <motion.div
                    key={order.order_id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                  >
                    <Card 
                      className={order.status === 'pending' ? 'border-amber-500/50' : ''}
                      data-testid={`order-${order.order_id}`}
                    >
                      <CardContent className="p-6">
                        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                          {/* Order Info */}
                          <div className="space-y-3">
                            <div className="flex items-center gap-3">
                              <h3 className="font-bold text-lg">
                                Order #{order.order_id.slice(-8)}
                              </h3>
                              <Badge className={getStatusBadge(order.status)}>
                                {order.status.replace('_', ' ')}
                              </Badge>
                              {order.is_donation && (
                                <Badge className="bg-pink-100 text-pink-700">Donation</Badge>
                              )}
                              {/* An order can reach the kitchen before its payment
                                  settles. Saying so lets the restaurant decide
                                  whether to start cooking; it is not a refusal. */}
                              {order.payment_status && order.payment_status !== 'paid' && (
                                <Badge className="bg-slate-100 text-slate-700" data-testid={`payment-${order.order_id}`}>
                                  Payment {order.payment_status}
                                </Badge>
                              )}
                            </div>
                            
                            {/* Items */}
                            <div className="flex flex-wrap gap-2">
                              {order.items?.map((item, idx) => (
                                <span key={idx} className="text-sm bg-secondary px-3 py-1 rounded-full">
                                  {item.quantity}x {item.name}
                                </span>
                              ))}
                            </div>
                            
                            <div className="flex items-center gap-4 text-sm text-muted-foreground">
                              <span className="flex items-center gap-1">
                                <Clock className="w-4 h-4" />
                                {new Date(order.created_at).toLocaleTimeString()}
                              </span>
                              <span className="font-mono font-semibold text-foreground">
                                ${order.total_amount?.toFixed(2)}
                              </span>
                            </div>
                          </div>
                          
                          {/* Actions */}
                          <div className="flex items-center gap-3">
                            {nextAction && (
                              <Button
                                onClick={() => handleUpdateStatus(order.order_id, nextAction.next)}
                                className={order.status === 'pending' ? 'bg-amber-600 hover:bg-amber-700' : ''}
                              >
                                <nextAction.icon className="w-4 h-4 mr-2" />
                                {nextAction.label}
                              </Button>
                            )}
                            
                            {order.status === 'pending' && (
                              <Button
                                variant="outline"
                                className="text-destructive"
                                onClick={() => handleUpdateStatus(order.order_id, 'cancelled')}
                              >
                                <XCircle className="w-4 h-4 mr-2" />
                                Cancel
                              </Button>
                            )}
                            
                            {order.status === 'ready' && (
                              <Badge className="bg-green-100 text-green-800 py-2">
                                <Truck className="w-4 h-4 mr-2" />
                                Waiting for driver
                              </Badge>
                            )}
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </motion.div>
                );
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default RestaurantOrders;
