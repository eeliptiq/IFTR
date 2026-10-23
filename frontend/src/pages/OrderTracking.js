import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Progress } from '../components/ui/progress';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  Package, Truck, CheckCircle, Clock, MapPin, 
  ChefHat, Navigation, Phone, DollarSign, AlertTriangle, Heart, RefreshCw
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// When the API says a delivery came back to the pool.
const formatWhen = (value) => (value ? new Date(value).toLocaleString() : '');

const OrderTracking = () => {
  const { orderId } = useParams();
  const { token } = useAuth();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tipDialog, setTipDialog] = useState(false);
  const [addTipAmount, setAddTipAmount] = useState('');
  const [issueDialog, setIssueDialog] = useState(false);
  const [issueText, setIssueText] = useState('');

  useEffect(() => {
    fetchOrder();
    const interval = setInterval(fetchOrder, 10000); // Poll every 10s
    return () => clearInterval(interval);
  }, [orderId]);

  const fetchOrder = async () => {
    try {
      const res = await axios.get(`${API}/orders/${orderId}`, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setOrder(res.data);
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddTip = async () => {
    const amount = parseFloat(addTipAmount);
    if (!amount || amount <= 0) {
      toast.error('Please enter a valid tip amount');
      return;
    }
    try {
      const res = await axios.post(`${API}/orders/${orderId}/add-tip`, 
        { amount },
        { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }
      );
      toast.success(`Added $${amount.toFixed(2)} tip! Total tip: $${res.data.total_tip.toFixed(2)}`);
      setTipDialog(false);
      setAddTipAmount('');
      fetchOrder();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to add tip');
    }
  };

  const handleReportIssue = async () => {
    if (!issueText.trim()) {
      toast.error('Please describe the issue');
      return;
    }
    try {
      await axios.post(`${API}/orders/${orderId}/report-issue`, 
        { description: issueText },
        { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }
      );
      toast.success('Issue reported. We\'ll look into it.');
      setIssueDialog(false);
      setIssueText('');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to report issue');
    }
  };

  const statusSteps = [
    { key: 'pending', label: 'Order Placed', icon: Package },
    { key: 'confirmed', label: 'Confirmed', icon: CheckCircle },
    { key: 'preparing', label: 'Preparing', icon: ChefHat },
    { key: 'ready', label: 'Ready', icon: Package },
    { key: 'picked_up', label: 'Picked Up', icon: Truck },
    { key: 'in_transit', label: 'On the Way', icon: Navigation },
    { key: 'delivered', label: 'Delivered', icon: CheckCircle }
  ];

  const getCurrentStepIndex = () => {
    if (!order) return 0;
    // A claimed order is still on the kitchen counter: the courier's half of
    // the trip starts at pickup, so 'assigned' has no step of its own and sits
    // where the food already is. Without this the stepper falls back to step
    // one and the order looks unplaced the moment a driver takes it.
    const key = order.status === 'assigned' ? 'ready' : order.status;
    const idx = statusSteps.findIndex(s => s.key === key);
    return idx >= 0 ? idx : 0;
  };

  const getProgress = () => {
    const current = getCurrentStepIndex();
    return ((current + 1) / statusSteps.length) * 100;
  };

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="h-4 bg-muted rounded w-full" />
          <div className="h-64 bg-muted rounded-xl" />
        </div>
      </div>
    );
  }

  if (!order) {
    return (
      <div className="p-6 md:p-8">
        <Card>
          <CardContent className="p-12 text-center">
            <Package className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">Order not found</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const currentStep = getCurrentStepIndex();
  // Oldest first, so the last entry is the most recent return.
  const latestReassignment = order.reassignments?.length
    ? order.reassignments[order.reassignments.length - 1]
    : null;

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="order-tracking-page">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Order #{order.order_id.slice(-8)}</h1>
        <p className="text-muted-foreground">
          {order.estimated_delivery_time 
            ? `Estimated delivery in ${order.estimated_delivery_time} minutes`
            : 'Tracking your order'
          }
        </p>
      </div>

      {/* Progress Bar */}
      <Card>
        <CardContent className="p-6">
          <div className="mb-4">
            <Progress value={getProgress()} className="h-2" />
          </div>
          
          {/* Status Steps */}
          <div className="flex justify-between">
            {statusSteps.map((step, idx) => {
              const isCompleted = idx <= currentStep;
              const isCurrent = idx === currentStep;
              
              return (
                <div key={step.key} className="flex flex-col items-center">
                  <motion.div
                    initial={{ scale: 0.8 }}
                    animate={{ 
                      scale: isCurrent ? 1.1 : 1,
                      opacity: isCompleted ? 1 : 0.4
                    }}
                    className={`w-10 h-10 rounded-full flex items-center justify-center ${
                      isCompleted 
                        ? isCurrent 
                          ? 'bg-primary text-primary-foreground' 
                          : 'bg-green-500 text-white'
                        : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    <step.icon className="w-5 h-5" />
                  </motion.div>
                  <span className={`text-xs mt-2 text-center hidden md:block ${
                    isCompleted ? 'text-foreground font-medium' : 'text-muted-foreground'
                  }`}>
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Current Status Message */}
          <motion.div
            key={order.status}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-6 p-4 rounded-xl bg-primary/10 text-center"
          >
            <p className="font-semibold text-lg">
              {order.status === 'pending' && 'Waiting for restaurant confirmation...'}
              {order.status === 'confirmed' && 'Restaurant confirmed your order!'}
              {order.status === 'preparing' && 'Your food is being prepared 👨‍🍳'}
              {order.status === 'ready' && 'Your order is ready for pickup!'}
              {order.status === 'assigned' && 'A driver is on the way to collect your order 🚗'}
              {order.status === 'picked_up' && 'Driver picked up your order 🚗'}
              {order.status === 'in_transit' && 'Your order is on the way! 🛵'}
              {order.status === 'delivered' && 'Order delivered! Enjoy your meal 🎉'}
              {order.status === 'cancelled' && 'Order was cancelled'}
            </p>
          </motion.div>
        </CardContent>
      </Card>

      {/* Order Details */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Items */}
        <Card>
          <CardContent className="p-6">
            <h3 className="font-semibold mb-4">Order Items</h3>
            <div className="space-y-3">
              {order.items?.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Badge variant="secondary">{item.quantity}x</Badge>
                    <span>{item.name}</span>
                  </div>
                  <span className="font-mono">${(item.price * item.quantity).toFixed(2)}</span>
                </div>
              ))}
              <div className="border-t border-border pt-3 mt-3">
                <div className="flex justify-between text-sm text-muted-foreground">
                  <span>Subtotal</span>
                  <span>${(order.subtotal ?? 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-sm text-muted-foreground">
                  <span>Delivery Fee</span>
                  <span>${order.delivery_fee?.toFixed(2) || '0.00'}</span>
                </div>
                {order.tip_amount > 0 && (
                  <div className="flex justify-between text-sm text-muted-foreground">
                    <span>Tip</span>
                    <span>${order.tip_amount.toFixed(2)}</span>
                  </div>
                )}
                <div className="flex justify-between font-semibold mt-2">
                  <span>Total</span>
                  <span className="font-mono">${(order.total_amount || 0).toFixed(2)}</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Delivery Info */}
        <Card>
          <CardContent className="p-6">
            <h3 className="font-semibold mb-4">Delivery Details</h3>
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <MapPin className="w-5 h-5 text-muted-foreground mt-0.5" />
                <div>
                  <p className="font-medium">Delivery Address</p>
                  <p className="text-sm text-muted-foreground">
                    {order.delivery_location?.address || 'Address encrypted for privacy'}
                  </p>
                </div>
              </div>
              
              {order.driver_id && (
                <div className="p-4 rounded-xl bg-secondary/50">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
                      <Truck className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                      <p className="font-medium">{order.driver_name || 'Driver Assigned'}</p>
                      <p className="text-sm text-muted-foreground">Your driver is on the way</p>
                    </div>
                  </div>
                </div>
              )}

              {/* A delivery that came back to the pool. The audit row behind it
                  names the administrator and the reason; the customer is told
                  only that the courier changed, never why. */}
              {latestReassignment && (
                <div
                  className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800"
                  data-testid="reassignment-notice"
                >
                  <div className="flex items-start gap-3">
                    <RefreshCw className="w-5 h-5 text-amber-600 mt-0.5" />
                    <div>
                      <p className="font-medium text-amber-800 dark:text-amber-200">
                        {order.driver_id
                          ? 'Your delivery changed drivers'
                          : 'Finding you another driver'}
                      </p>
                      <p className="text-sm text-amber-700 dark:text-amber-300">
                        {order.driver_id
                          ? `${order.driver_name || 'A new driver'} is taking over your delivery.`
                          : 'The delivery came back to the courier pool, so another driver can pick it up.'}
                      </p>
                      {latestReassignment.returned_at && (
                        <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                          Returned to the pool {formatWhen(latestReassignment.returned_at)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {order.is_donation && (
                <Badge className="bg-pink-100 text-pink-700">
                  This is a donation order ❤️
                </Badge>
              )}

              {/* Tip Information */}
              <div className="p-4 rounded-xl bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-green-800 dark:text-green-200 flex items-center gap-2">
                      <Heart className="w-4 h-4" /> Driver Tip
                    </p>
                    <p className="text-sm text-green-600 dark:text-green-400">
                      Initial: ${(order.tip_amount || 0).toFixed(2)}
                      {(order.additional_tip || 0) > 0 && ` + $${order.additional_tip.toFixed(2)} added`}
                    </p>
                  </div>
                  <p className="text-xl font-bold text-green-600 font-mono">
                    ${((order.tip_amount || 0) + (order.additional_tip || 0)).toFixed(2)}
                  </p>
                </div>
                {order.status !== 'cancelled' && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full mt-3 border-green-300 text-green-700 hover:bg-green-100"
                    onClick={() => setTipDialog(true)}
                  >
                    <DollarSign className="w-4 h-4 mr-2" />
                    Add More Tip
                  </Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Action Buttons */}
      {order.status !== 'delivered' && order.status !== 'cancelled' && (
        <Card>
          <CardContent className="p-4">
            <div className="flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setIssueDialog(true)}
              >
                <AlertTriangle className="w-4 h-4 mr-2" />
                Report Issue
              </Button>
              {order.status === 'pending' && (
                <Button
                  variant="destructive"
                  className="flex-1"
                  onClick={async () => {
                    try {
                      await axios.put(`${API}/orders/${orderId}/status?status=cancelled`, {}, {
                        headers: { Authorization: `Bearer ${token}` },
                        withCredentials: true
                      });
                      toast.success('Order cancelled');
                      fetchOrder();
                    } catch (error) {
                      toast.error('Cannot cancel this order');
                    }
                  }}
                >
                  Cancel Order
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add Tip Dialog */}
      <Dialog open={tipDialog} onOpenChange={setTipDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add a Tip for Your Driver</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            <p className="text-sm text-muted-foreground">
              Show appreciation for great service! Tips can only be added, never reduced.
            </p>
            <div className="grid grid-cols-4 gap-2">
              {[1, 2, 5, 10].map((amt) => (
                <Button
                  key={amt}
                  variant={addTipAmount === String(amt) ? 'default' : 'outline'}
                  onClick={() => setAddTipAmount(String(amt))}
                >
                  ${amt}
                </Button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">$</span>
              <Input
                type="number"
                min="0"
                step="0.5"
                value={addTipAmount}
                onChange={(e) => setAddTipAmount(e.target.value)}
                placeholder="Custom amount"
              />
            </div>
            <Button className="w-full" onClick={handleAddTip} disabled={!addTipAmount}>
              Add ${addTipAmount || '0'} Tip
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Report Issue Dialog */}
      <Dialog open={issueDialog} onOpenChange={setIssueDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Report an Issue</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            <p className="text-sm text-muted-foreground">
              Let us know what went wrong and we'll help resolve it.
            </p>
            <textarea
              className="w-full p-3 rounded-lg border border-border bg-background min-h-[100px]"
              placeholder="Describe the issue..."
              value={issueText}
              onChange={(e) => setIssueText(e.target.value)}
            />
            <Button className="w-full" onClick={handleReportIssue} disabled={!issueText.trim()}>
              Submit Report
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default OrderTracking;
