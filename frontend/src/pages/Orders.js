import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  ShoppingBag, Clock, MapPin, Truck, CheckCircle, 
  XCircle, ChevronRight, RefreshCw, DollarSign, AlertTriangle, Heart, CreditCard, Bitcoin
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const Orders = () => {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all');
  
  // Tip dialog state
  const [tipDialog, setTipDialog] = useState({ open: false, orderId: null });
  const [tipAmount, setTipAmount] = useState('');
  
  // Issue dialog state
  const [issueDialog, setIssueDialog] = useState({ open: false, orderId: null });
  const [issueText, setIssueText] = useState('');
  // The order whose Checkout page is being opened, so a double-click cannot
  // send the customer to two payment pages.
  const [payingOrderId, setPayingOrderId] = useState(null);
  // Whether this deployment offers Bitcoin/Monero at all. Asked once: the
  // button is either there or it is not, and a failed request leaves it out
  // rather than offering a page that cannot quote a price.
  const [cryptoEnabled, setCryptoEnabled] = useState(false);

  useEffect(() => {
    fetchOrders();
  }, [activeTab]);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/payments/methods`, {
      headers: { Authorization: `Bearer ${token}` },
      withCredentials: true
    }).then((res) => {
      if (!cancelled) setCryptoEnabled(Boolean(res.data?.crypto?.enabled));
    }).catch(() => {
      // Cards are the default; a methods endpoint that is down should not put
      // an error in front of somebody who only wants to pay.
    });
    return () => { cancelled = true; };
  }, [token]);

  const fetchOrders = async () => {
    try {
      const params = activeTab !== 'all' ? `?status=${activeTab}` : '';
      const res = await axios.get(`${API}/orders${params}`, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setOrders(res.data);
    } catch (error) {
      toast.error('Failed to load orders');
    } finally {
      setLoading(false);
    }
  };

  const handleAddTip = async () => {
    const amount = parseFloat(tipAmount);
    if (!amount || amount <= 0) {
      toast.error('Please enter a valid tip amount');
      return;
    }
    try {
      const res = await axios.post(`${API}/orders/${tipDialog.orderId}/add-tip`, 
        { amount },
        { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }
      );
      toast.success(`Added $${amount.toFixed(2)} tip! Total tip: $${res.data.total_tip.toFixed(2)}`);
      setTipDialog({ open: false, orderId: null });
      setTipAmount('');
      fetchOrders();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to add tip');
    }
  };

  const handlePay = async (event, order) => {
    event.stopPropagation();
    if (payingOrderId) return;

    setPayingOrderId(order.order_id);
    try {
      const res = await axios.post(`${API}/payments/checkout`, {
        order_id: order.order_id,
        origin_url: window.location.origin
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      if (res.data?.url) {
        window.location.href = res.data.url;
        return;
      }
      toast.error('The payment page could not be opened. Nothing was charged.');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Could not start payment');
    } finally {
      setPayingOrderId(null);
    }
  };

  const handleReportIssue = async () => {
    if (!issueText.trim()) {
      toast.error('Please describe the issue');
      return;
    }
    try {
      await axios.post(`${API}/orders/${issueDialog.orderId}/report-issue`, 
        { description: issueText },
        { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }
      );
      toast.success('Issue reported. We\'ll look into it.');
      setIssueDialog({ open: false, orderId: null });
      setIssueText('');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to report issue');
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'delivered':
        return <CheckCircle className="w-5 h-5 text-green-500" />;
      case 'cancelled':
        return <XCircle className="w-5 h-5 text-red-500" />;
      case 'in_transit':
      case 'picked_up':
        return <Truck className="w-5 h-5 text-blue-500" />;
      default:
        return <Clock className="w-5 h-5 text-amber-500" />;
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'delivered':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400';
      case 'cancelled':
        return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400';
      case 'in_transit':
      case 'picked_up':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400';
      default:
        return 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400';
    }
  };

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="orders-page">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">My Orders</h1>
        <Button variant="outline" size="icon" onClick={fetchOrders}>
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-4 lg:w-auto lg:grid-cols-none lg:inline-flex">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="in_transit">In Transit</TabsTrigger>
          <TabsTrigger value="delivered">Delivered</TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} className="mt-6">
          {loading ? (
            <div className="space-y-4">
              {[...Array(3)].map((_, i) => (
                <Card key={i} className="animate-pulse">
                  <CardContent className="p-6">
                    <div className="h-24 bg-muted rounded" />
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : orders.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center">
                <ShoppingBag className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-muted-foreground">No orders found</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {orders.map((order, i) => (
                <motion.div
                  key={order.order_id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                >
                  <Card className="order-card" data-testid={`order-${order.order_id}`}>
                    <CardContent className="p-6">
                      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                        <div className="flex items-start gap-4">
                          <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
                            {getStatusIcon(order.status)}
                          </div>
                          <div>
                            <div className="flex items-center gap-3">
                              <h3 className="font-bold">Order #{order.order_id.slice(-8)}</h3>
                              <Badge className={getStatusColor(order.status)}>
                                {order.status.replace('_', ' ')}
                              </Badge>
                              {order.is_donation && (
                                <Badge variant="secondary" className="bg-pink-100 text-pink-700">
                                  Donation
                                </Badge>
                              )}
                            </div>
                            <p className="text-sm text-muted-foreground mt-1">
                              {order.items?.length || 0} items • {new Date(order.created_at).toLocaleDateString()}
                            </p>
                          </div>
                        </div>
                        
                        <div className="flex items-center gap-4">
                          <div className="text-right">
                            <p className="text-2xl font-bold font-mono">
                              ${(order.total_amount || 0).toFixed(2)}
                            </p>
                            <p className={`text-xs ${order.payment_status === 'paid' ? 'text-green-600' : 'text-muted-foreground'}`}>
                              {order.payment_status === 'paid'
                                ? 'Paid'
                                : order.payment_status === 'failed'
                                  ? 'Payment failed'
                                  : 'Payment pending'}
                            </p>
                          </div>
                          <ChevronRight className="w-5 h-5 text-muted-foreground" />
                        </div>
                      </div>

                      {/* Order Items Preview */}
                      <div className="mt-4 pt-4 border-t border-border">
                        <div className="flex flex-wrap gap-2">
                          {order.items?.slice(0, 3).map((item, idx) => (
                            <span key={idx} className="text-sm bg-secondary px-3 py-1 rounded-full">
                              {item.quantity}x {item.name}
                            </span>
                          ))}
                          {order.items?.length > 3 && (
                            <span className="text-sm text-muted-foreground">
                              +{order.items.length - 3} more
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Tip Info & Action Buttons */}
                      <div className="mt-4 pt-4 border-t border-border flex flex-wrap items-center justify-between gap-3">
                        {/* Show tip info */}
                        <div className="flex items-center gap-2 text-sm">
                          <Heart className="w-4 h-4 text-green-500" />
                          <span className="text-muted-foreground">
                            Tip: <span className="font-semibold text-green-600">${((order.tip_amount || 0) + (order.additional_tip || 0)).toFixed(2)}</span>
                          </span>
                        </div>

                        {/* Action Buttons */}
                        <div className="flex gap-2">
                          {order.status !== 'cancelled' && (
                            <>
                              {/* A cancelled Checkout leaves the order unpaid.
                                  This is where the customer comes back to pay. */}
                              {order.payment_status !== 'paid' && order.status !== 'delivered' && (
                                <Button
                                  size="sm"
                                  onClick={(e) => handlePay(e, order)}
                                  disabled={payingOrderId === order.order_id}
                                  data-testid={`pay-${order.order_id}`}
                                >
                                  <CreditCard className="w-4 h-4 mr-1" />
                                  {payingOrderId === order.order_id ? 'Opening…' : 'Pay'}
                                </Button>
                              )}
                              {cryptoEnabled && order.payment_status !== 'paid' && order.status !== 'delivered' && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="text-orange-600 border-orange-200 hover:bg-orange-50"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/payment/crypto/${order.order_id}`);
                                  }}
                                  data-testid={`pay-crypto-${order.order_id}`}
                                >
                                  <Bitcoin className="w-4 h-4 mr-1" />
                                  Crypto
                                </Button>
                              )}
                              {order.payment_status !== 'paid' && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="text-green-600 border-green-200 hover:bg-green-50"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setTipDialog({ open: true, orderId: order.order_id });
                                  }}
                                  data-testid={`add-tip-${order.order_id}`}
                                >
                                  <DollarSign className="w-4 h-4 mr-1" />
                                  Add Tip
                                </Button>
                              )}
                              <Button
                                variant="outline"
                                size="sm"
                                className="text-amber-600 border-amber-200 hover:bg-amber-50"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setIssueDialog({ open: true, orderId: order.order_id });
                                }}
                                data-testid={`report-issue-${order.order_id}`}
                              >
                                <AlertTriangle className="w-4 h-4 mr-1" />
                                Report Issue
                              </Button>
                            </>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => navigate(`/orders/${order.order_id}`)}
                          >
                            Track
                            <ChevronRight className="w-4 h-4 ml-1" />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Add Tip Dialog */}
      <Dialog open={tipDialog.open} onOpenChange={(open) => setTipDialog({ ...tipDialog, open })}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Heart className="w-5 h-5 text-green-500" />
              Add a Tip for Your Driver
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            <p className="text-sm text-muted-foreground">
              Show appreciation for great service! Tips can only be added, never reduced.
            </p>
            <div className="grid grid-cols-4 gap-2">
              {[1, 2, 5, 10].map((amt) => (
                <Button
                  key={amt}
                  variant={tipAmount === String(amt) ? 'default' : 'outline'}
                  onClick={() => setTipAmount(String(amt))}
                  className="h-12"
                >
                  ${amt}
                </Button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-lg">$</span>
              <Input
                type="number"
                min="0"
                step="0.5"
                value={tipAmount}
                onChange={(e) => setTipAmount(e.target.value)}
                placeholder="Custom amount"
                className="text-lg"
              />
            </div>
            <Button className="w-full h-12 bg-green-600 hover:bg-green-700" onClick={handleAddTip} disabled={!tipAmount}>
              <DollarSign className="w-4 h-4 mr-2" />
              Add ${tipAmount || '0'} Tip
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Report Issue Dialog */}
      <Dialog open={issueDialog.open} onOpenChange={(open) => setIssueDialog({ ...issueDialog, open })}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-500" />
              Report an Issue
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            <p className="text-sm text-muted-foreground">
              Let us know what went wrong and we'll help resolve it.
            </p>
            <div className="space-y-2">
              <p className="text-sm font-medium">Common issues:</p>
              <div className="flex flex-wrap gap-2">
                {['Wrong items', 'Missing items', 'Late delivery', 'Cold food', 'Damaged packaging', 'Driver issue'].map((issue) => (
                  <Button
                    key={issue}
                    variant="outline"
                    size="sm"
                    onClick={() => setIssueText(issue)}
                    className={issueText === issue ? 'border-primary bg-primary/5' : ''}
                  >
                    {issue}
                  </Button>
                ))}
              </div>
            </div>
            <textarea
              className="w-full p-3 rounded-lg border border-border bg-background min-h-[100px] text-sm"
              placeholder="Describe the issue in detail..."
              value={issueText}
              onChange={(e) => setIssueText(e.target.value)}
            />
            <Button className="w-full h-12" onClick={handleReportIssue} disabled={!issueText.trim()}>
              Submit Report
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Orders;
