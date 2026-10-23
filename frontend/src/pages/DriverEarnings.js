import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs';
import axios from 'axios';
import { DollarSign, TrendingUp, Truck, Clock } from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const EMPTY_PERIOD = { deliveries: 0, delivery_fees: 0, tips: 0, earnings: 0 };

const DriverEarnings = () => {
  const { token } = useAuth();
  const [earnings, setEarnings] = useState({
    total_deliveries: 0,
    total_earnings: 0,
    surplus_runs: 0,
    today: EMPTY_PERIOD,
    week: EMPTY_PERIOD,
    month: EMPTY_PERIOD,
    recent: []
  });
  const [period, setPeriod] = useState('week');
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    fetchEarnings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchEarnings = async () => {
    try {
      const res = await axios.get(`${API}/drivers/earnings`, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setEarnings({
        ...res.data,
        today: res.data.today || EMPTY_PERIOD,
        week: res.data.week || EMPTY_PERIOD,
        month: res.data.month || EMPTY_PERIOD,
        recent: res.data.recent || []
      });
      setUnavailable(false);
    } catch (error) {
      // Zeros rather than invented trips: this page is a record of work done.
      setUnavailable(true);
    } finally {
      setLoading(false);
    }
  };

  const currentPeriod = earnings[period] || EMPTY_PERIOD;

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="grid grid-cols-3 gap-4">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-32 bg-muted rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="driver-earnings-page">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Your Earnings</h1>
        <p className="text-muted-foreground">
          What your completed trips were worth. Tips are included; nothing is
          paid out until driver payouts are connected.
        </p>
        {unavailable && (
          <p className="mt-2 text-sm text-destructive">
            Earnings could not be loaded right now.
          </p>
        )}
      </div>

      {/* Period Tabs */}
      <Tabs value={period} onValueChange={setPeriod}>
        <TabsList>
          <TabsTrigger value="today">Today</TabsTrigger>
          <TabsTrigger value="week">Last 7 Days</TabsTrigger>
          <TabsTrigger value="month">Last 30 Days</TabsTrigger>
        </TabsList>
      </Tabs>

      {/* Main Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <motion.div
          key={`earnings-${period}`}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card className="bg-gradient-to-br from-green-500/10 to-green-600/5 border-green-500/20">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <DollarSign className="w-8 h-8 text-green-600" />
                <Badge className="bg-green-100 text-green-700">
                  {currentPeriod.deliveries} trip{currentPeriod.deliveries === 1 ? '' : 's'}
                </Badge>
              </div>
              <p className="text-4xl font-bold font-mono text-green-600">
                ${currentPeriod.earnings.toFixed(2)}
              </p>
              <p className="text-sm text-muted-foreground mt-1">Trip Pay</p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <Truck className="w-8 h-8 text-blue-600" />
              </div>
              <p className="text-4xl font-bold font-mono">{currentPeriod.deliveries}</p>
              <p className="text-sm text-muted-foreground mt-1">Deliveries</p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <TrendingUp className="w-8 h-8 text-amber-600" />
              </div>
              <p className="text-4xl font-bold font-mono">
                ${currentPeriod.deliveries > 0
                  ? (currentPeriod.earnings / currentPeriod.deliveries).toFixed(2)
                  : '0.00'}
              </p>
              <p className="text-sm text-muted-foreground mt-1">Avg per Delivery</p>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Lifetime and volunteer work */}
      <Card>
        <CardContent className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
              <p className="text-sm text-muted-foreground">Total Deliveries</p>
              <p className="text-3xl font-bold font-mono">{earnings.total_deliveries}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Lifetime Trip Pay</p>
              <p className="text-3xl font-bold font-mono text-green-600">
                ${earnings.total_earnings.toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Volunteer Runs</p>
              <p className="text-3xl font-bold font-mono">{earnings.surplus_runs}</p>
              <p className="text-xs text-muted-foreground mt-1">
                Surplus rescues pay nothing and are counted separately.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Recent Deliveries */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Deliveries</CardTitle>
        </CardHeader>
        <CardContent>
          {earnings.recent.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No completed trips yet. Accept a job from the deliveries board and
              it will appear here once delivered.
            </p>
          ) : (
            <div className="space-y-4">
              {earnings.recent.map((delivery, i) => (
                <motion.div
                  key={delivery.order_id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="flex items-center justify-between p-4 rounded-xl bg-secondary/50"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                      <Truck className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                      <p className="font-medium">
                        Order {delivery.order_id.slice(-6)}
                      </p>
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Clock className="w-3 h-3" />
                        {new Date(delivery.delivered_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="font-mono font-bold text-green-600">
                      +${delivery.earnings.toFixed(2)}
                    </p>
                    {delivery.tips > 0 && (
                      <p className="text-xs text-muted-foreground">
                        incl. ${delivery.tips.toFixed(2)} tip
                      </p>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Earnings Breakdown */}
      <Card>
        <CardHeader>
          <CardTitle>Earnings Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex justify-between items-center p-3 rounded-lg bg-secondary/30">
              <span>Delivery Fees</span>
              <span className="font-mono font-semibold">
                ${currentPeriod.delivery_fees.toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between items-center p-3 rounded-lg bg-secondary/30">
              <span>Tips</span>
              <span className="font-mono font-semibold">
                ${currentPeriod.tips.toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between items-center p-4 rounded-lg bg-green-500/10 border border-green-500/20">
              <span className="font-semibold">Total</span>
              <span className="font-mono font-bold text-green-600 text-xl">
                ${currentPeriod.earnings.toFixed(2)}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default DriverEarnings;
