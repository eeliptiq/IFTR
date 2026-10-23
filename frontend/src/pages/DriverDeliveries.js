import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  Truck, MapPin, Clock, DollarSign, CheckCircle, 
  Navigation, Phone, Package, ArrowRight, RefreshCw, Car, Bike, User,
  Heart, DoorOpen, Building, MessageSquare, Filter, ArrowUp, RotateCcw
} from 'lucide-react';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '../components/ui/alert-dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '../components/ui/tabs';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// The eight compass points, spelled out for the sentence under the arrow.
const COMPASS_WORDS = {
  N: 'north',
  NE: 'north-east',
  E: 'east',
  SE: 'south-east',
  S: 'south',
  SW: 'south-west',
  W: 'west',
  NW: 'north-west',
};

const INSTRUCTION_LABELS = {
  'hand_to_customer': { label: 'Hand to customer', icon: User },
  'leave_at_door': { label: 'Leave at door', icon: DoorOpen },
  'meet_outside': { label: 'Meet outside', icon: MapPin },
  'meet_in_lobby': { label: 'Meet in lobby', icon: Building },
  'other': { label: 'See notes', icon: MessageSquare },
};

const DriverDeliveries = () => {
  const { token } = useAuth();
  const [availableOrders, setAvailableOrders] = useState([]);
  const [surplusDeliveries, setSurplusDeliveries] = useState([]);
  const [activeSurplusRuns, setActiveSurplusRuns] = useState([]);
  const [activeDelivery, setActiveDelivery] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isAvailable, setIsAvailable] = useState(true);
  const [isRegistered, setIsRegistered] = useState(true);
  const [registering, setRegistering] = useState(false);
  const [regForm, setRegForm] = useState({ vehicle_type: 'car', license_number: '' });
  const [activeTab, setActiveTab] = useState('all');
  // Jobs this driver turned down before, brought back on request. They are only
  // ever offered again if nobody has taken them in the meantime.
  const [showRejected, setShowRejected] = useState(false);
  
  // Vehicle management
  const [driverProfile, setDriverProfile] = useState(null);
  const [vehicleDialog, setVehicleDialog] = useState(false);
  const [newVehicle, setNewVehicle] = useState({ vehicle_type: 'car', license_number: '' });

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [showRejected]);

  const fetchData = async () => {
    try {
      const headers = { Authorization: `Bearer ${token}` };
      
      const [ordersRes, surplusRes, activeSurplusRes, activeRes, profileRes] = await Promise.all([
        axios.get(`${API}/drivers/available-orders?include_rejected=${showRejected}`, { headers, withCredentials: true }),
        axios.get(`${API}/drivers/surplus-deliveries`, { headers, withCredentials: true }).catch(() => ({ data: [] })),
        axios.get(`${API}/drivers/active-surplus`, { headers, withCredentials: true }).catch(() => ({ data: [] })),
        axios.get(`${API}/drivers/active-delivery`, { headers, withCredentials: true }),
        axios.get(`${API}/drivers/profile`, { headers, withCredentials: true }).catch(() => ({ data: null }))
      ]);
      
      setAvailableOrders(ordersRes.data);
      setSurplusDeliveries(surplusRes.data);
      setActiveSurplusRuns(activeSurplusRes.data);
      setActiveDelivery(activeRes.data);
      setDriverProfile(profileRes.data);
      setIsRegistered(true);
    } catch (error) {
      console.error('Fetch error:', error);
      // Check if error is "Driver not found" - means not registered
      if (error.response?.status === 404 && error.response?.data?.detail === "Driver not found") {
        setIsRegistered(false);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateVehicle = async () => {
    try {
      await axios.put(`${API}/drivers/vehicle`, newVehicle, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success(`Vehicle updated to ${newVehicle.vehicle_type}`);
      setVehicleDialog(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to update vehicle');
    }
  };

  const handleRegisterDriver = async () => {
    if (!regForm.license_number) {
      toast.error('Please enter your license number');
      return;
    }
    setRegistering(true);
    try {
      await axios.post(`${API}/drivers/register`, regForm, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success('Registered as driver! You can now accept deliveries.');
      setIsRegistered(true);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Registration failed');
    } finally {
      setRegistering(false);
    }
  };

  const handleAcceptOrder = async (orderId) => {
    try {
      await axios.post(`${API}/drivers/accept-order/${orderId}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success('Order accepted! Navigate to pickup location.');
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to accept order');
    }
  };

  const handleDeclineOrder = async (orderId) => {
    try {
      await axios.post(`${API}/drivers/decline-order/${orderId}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      // Removed here rather than waiting for the next poll, so the card goes
      // away when the driver taps, not up to 30 seconds later.
      setAvailableOrders((orders) => orders.filter((order) => order.order_id !== orderId));
      toast.success('Order passed');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to pass on order');
    }
  };

  const handleVolunteerSurplus = async (deliveryId) => {
    try {
      const res = await axios.post(`${API}/drivers/volunteer-surplus/${deliveryId}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success(`Thank you for volunteering! 💚 ETA: ${res.data.estimated_time} min`);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to volunteer');
    }
  };

  const handleUpdateSurplusStatus = async (deliveryId, status) => {
    try {
      const res = await axios.put(
        `${API}/drivers/surplus-deliveries/${deliveryId}/status?status=${status}`,
        {},
        { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }
      );
      if (status === 'delivered') {
        const portions = res.data.quantity;
        toast.success(
          `Surplus delivered! ${portions} portion${portions === 1 ? '' : 's'} received.`
        );
      } else {
        toast.success(`Surplus run marked as ${status.replace('_', ' ')}`);
      }
      fetchData();
    } catch (error) {
      toast.error(
        error.response?.data?.detail || 'Failed to update surplus delivery'
      );
    }
  };

  const handleAbandonSurplus = async (deliveryId) => {
    try {
      await axios.post(
        `${API}/drivers/surplus-deliveries/${deliveryId}/abandon`,
        {},
        { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }
      );
      toast.success('Run returned to the volunteer pool');
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to return the run');
    }
  };

  const handleUpdateStatus = async (orderId, status) => {
    try {
      await axios.put(`${API}/orders/${orderId}/status?status=${status}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success(`Order marked as ${status.replace('_', ' ')}`);
      fetchData();
    } catch (error) {
      toast.error('Failed to update status');
    }
  };

  const toggleAvailability = async () => {
    try {
      const newStatus = !isAvailable;
      await axios.put(`${API}/drivers/availability?is_available=${newStatus}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setIsAvailable(newStatus);
      toast.success(newStatus ? 'You are now online' : 'You are now offline');
    } catch (error) {
      toast.error('Failed to update availability');
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

  // Show registration form if not registered as driver
  if (!isRegistered) {
    return (
      <div className="p-6 md:p-8 max-w-xl mx-auto" data-testid="driver-registration">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <Truck className="w-6 h-6 text-primary" />
                Become a Driver
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <p className="text-muted-foreground">
                Register as a driver to start accepting deliveries and earning money.
              </p>
              
              <div className="space-y-2">
                <Label>Vehicle Type</Label>
                <Select 
                  value={regForm.vehicle_type} 
                  onValueChange={(v) => setRegForm({...regForm, vehicle_type: v})}
                >
                  <SelectTrigger data-testid="vehicle-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="car">
                      <span className="flex items-center gap-2"><Car className="w-4 h-4" /> Car</span>
                    </SelectItem>
                    <SelectItem value="bike">
                      <span className="flex items-center gap-2"><Bike className="w-4 h-4" /> Bicycle</span>
                    </SelectItem>
                    <SelectItem value="motorcycle">
                      <span className="flex items-center gap-2"><Truck className="w-4 h-4" /> Motorcycle</span>
                    </SelectItem>
                    <SelectItem value="walk">
                      <span className="flex items-center gap-2"><User className="w-4 h-4" /> On Foot</span>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="license">License/ID Number</Label>
                <Input
                  id="license"
                  value={regForm.license_number}
                  onChange={(e) => setRegForm({...regForm, license_number: e.target.value})}
                  placeholder="Enter your license number"
                  data-testid="license-input"
                />
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <span className="text-green-500">🔒</span>
                  Your license number is encrypted and stored securely
                </p>
              </div>

              <Button 
                onClick={handleRegisterDriver} 
                className="w-full"
                disabled={registering}
                data-testid="register-driver-btn"
              >
                {registering ? 'Registering...' : 'Register as Driver'}
              </Button>
            </CardContent>
          </Card>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="driver-deliveries-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Deliveries</h1>
          <p className="text-muted-foreground">
            {activeDelivery ? 'Complete your current delivery' : 'Accept orders to start earning'}
          </p>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <Button
            variant={showRejected ? 'default' : 'outline'}
            onClick={() => setShowRejected((shown) => !shown)}
            data-testid="show-rejected-orders"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            {showRejected ? 'Hide rejected orders' : 'Show rejected orders'}
          </Button>
          <Button variant="outline" size="icon" onClick={fetchData}>
            <RefreshCw className="w-4 h-4" />
          </Button>
          <Button
            variant={isAvailable ? 'default' : 'outline'}
            onClick={toggleAvailability}
            className={isAvailable ? 'bg-green-600 hover:bg-green-700' : ''}
            data-testid="availability-toggle"
          >
            {isAvailable ? 'Online' : 'Offline'}
          </Button>
        </div>
      </div>

      {/* Active Delivery */}
      {activeDelivery && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card className="border-2 border-primary bg-primary/5">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <Truck className="w-5 h-5 text-primary" />
                  Active Delivery
                  {activeDelivery.is_volunteer_delivery && (
                    <Badge className="bg-pink-100 text-pink-700 ml-2">
                      <Heart className="w-3 h-3 mr-1" /> Volunteer
                    </Badge>
                  )}
                </CardTitle>
                <Badge className="bg-green-100 text-green-800">
                  {activeDelivery.status.replace('_', ' ')}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Delivery Instructions - IMPORTANT */}
              {(activeDelivery.delivery_instruction_type || activeDelivery.delivery_instructions) && (
                <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
                  <h3 className="font-semibold flex items-center gap-2 text-amber-800 dark:text-amber-200 mb-2">
                    <MessageSquare className="w-4 h-4" />
                    Delivery Instructions
                  </h3>
                  <div className="flex items-center gap-2 mb-2">
                    {(() => {
                      const instruction = INSTRUCTION_LABELS[activeDelivery.delivery_instruction_type] || INSTRUCTION_LABELS['hand_to_customer'];
                      const Icon = instruction.icon;
                      return (
                        <Badge variant="secondary" className="bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200">
                          <Icon className="w-3 h-3 mr-1" />
                          {instruction.label}
                        </Badge>
                      );
                    })()}
                  </div>
                  {activeDelivery.delivery_instructions && (
                    <p className="text-sm text-amber-700 dark:text-amber-300">
                      "{activeDelivery.delivery_instructions}"
                    </p>
                  )}
                </div>
              )}

              {/* Handling plan - what the order asks of the ride */}
              {(activeDelivery.handling_notes || []).length > 0 && (
                <div
                  className="p-4 rounded-xl bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800"
                  data-testid="handling-plan"
                >
                  <h3 className="font-semibold flex items-center gap-2 text-blue-800 dark:text-blue-200 mb-2">
                    <Package className="w-4 h-4" />
                    Special Handling
                    {activeDelivery.requires_cup_holder && (
                      <Badge className="bg-blue-600 text-white">Cup holder needed</Badge>
                    )}
                  </h3>
                  <ul className="space-y-1 text-sm text-blue-700 dark:text-blue-300">
                    {activeDelivery.handling_notes.map((note, idx) => (
                      <li key={idx} className="flex items-start gap-2">
                        <span className="mt-0.5">•</span>
                        <span>{note}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="grid md:grid-cols-2 gap-6">
                {/* Pickup Info */}
                <div className="space-y-3">
                  <h3 className="font-semibold flex items-center gap-2">
                    <Package className="w-4 h-4 text-orange-500" />
                    Pickup Location
                  </h3>
                  <div className="p-4 rounded-xl bg-secondary">
                    <p className="font-medium">Restaurant</p>
                    <p className="text-sm text-muted-foreground">
                      {activeDelivery.pickup_location?.address || 'Address encrypted'}
                    </p>
                  </div>
                </div>

                {/* Delivery Info */}
                <div className="space-y-3">
                  <h3 className="font-semibold flex items-center gap-2">
                    <MapPin className="w-4 h-4 text-green-500" />
                    Delivery Location
                  </h3>
                  <div className="p-4 rounded-xl bg-secondary">
                    <p className="font-medium">Customer</p>
                    <p className="text-sm text-muted-foreground">
                      {activeDelivery.delivery_location?.address || 'Address encrypted'}
                    </p>
                  </div>
                </div>
              </div>

              {/* Order Details */}
              <div className="p-4 rounded-xl bg-secondary/50">
                <p className="text-sm text-muted-foreground mb-2">Order Items</p>
                <div className="flex flex-wrap gap-2">
                  {activeDelivery.items?.map((item, idx) => (
                    <Badge key={idx} variant="secondary">
                      {item.is_drink && !item.is_sealed ? '🥤 ' : ''}{item.quantity}x {item.name}
                    </Badge>
                  ))}
                </div>
              </div>

              {/* Actions */}
              <div className="flex flex-wrap gap-3">
                {activeDelivery.status === 'assigned' && (
                  <Button
                    onClick={() => handleUpdateStatus(activeDelivery.order_id, 'picked_up')}
                    className="flex-1"
                    data-testid="picked-up-button"
                  >
                    <Package className="w-4 h-4 mr-2" />
                    I have the food
                  </Button>
                )}
                {activeDelivery.status === 'picked_up' && (
                  <Button
                    onClick={() => handleUpdateStatus(activeDelivery.order_id, 'in_transit')}
                    className="flex-1"
                    data-testid="start-delivery-button"
                  >
                    <Navigation className="w-4 h-4 mr-2" />
                    Start Delivery
                  </Button>
                )}
                {activeDelivery.status === 'in_transit' && (
                  <Button
                    onClick={() => handleUpdateStatus(activeDelivery.order_id, 'delivered')}
                    className="flex-1 bg-green-600 hover:bg-green-700"
                    data-testid="complete-delivery-button"
                  >
                    <CheckCircle className="w-4 h-4 mr-2" />
                    Complete Delivery
                  </Button>
                )}
              </div>

              {/* Earnings Preview */}
              <div className="flex items-center justify-between p-4 rounded-xl bg-green-500/10 border border-green-500/20">
                <span className="text-sm font-medium">
                  {activeDelivery.is_volunteer_delivery ? 'Volunteer Delivery' : 'Delivery Fee'}
                </span>
                <span className="text-xl font-bold text-green-600 font-mono">
                  {activeDelivery.is_volunteer_delivery ? '💚 Free' : `$${activeDelivery.delivery_fee?.toFixed(2) || '2.99'}`}
                </span>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Volunteer Runs in hand - a claimed run is work, not a board card. */}
      {activeSurplusRuns.map((run) => (
        <ActiveSurplusRunCard
          key={run.delivery_id}
          run={run}
          onUpdate={handleUpdateSurplusStatus}
          onAbandon={handleAbandonSurplus}
        />
      ))}

      {/* Available Orders */}
      {!activeDelivery && (
        <div className="space-y-4">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList className="grid w-full grid-cols-2 mb-4">
              <TabsTrigger value="all" className="flex items-center gap-2">
                <Package className="w-4 h-4" />
                All Orders ({availableOrders.length})
              </TabsTrigger>
              <TabsTrigger value="volunteer" className="flex items-center gap-2">
                <Heart className="w-4 h-4" />
                Volunteer ({surplusDeliveries.length})
              </TabsTrigger>
            </TabsList>
            
            <TabsContent value="all">
              {availableOrders.length === 0 ? (
                <Card>
                  <CardContent className="p-12 text-center">
                    <Truck className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                    <p className="text-muted-foreground">No orders available right now</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      Stay online and we'll notify you when orders come in
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <div className="grid gap-4">
                  {availableOrders.map((order, i) => (
                    <OrderCard 
                      key={order.order_id} 
                      order={order} 
                      index={i}
                      onAccept={handleAcceptOrder}
                      onDecline={handleDeclineOrder}
                    />
                  ))}
                </div>
              )}
            </TabsContent>
            
            <TabsContent value="volunteer">
              <div className="mb-4 p-4 rounded-xl bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800">
                <p className="text-sm text-green-700 dark:text-green-300 flex items-center gap-2">
                  <Heart className="w-4 h-4" />
                  Volunteer to deliver surplus food from restaurants to local organizations. No pay, but you'll make a real difference!
                </p>
              </div>
              {surplusDeliveries.length === 0 ? (
                <Card>
                  <CardContent className="p-12 text-center">
                    <Heart className="w-12 h-12 text-green-300 mx-auto mb-4" />
                    <p className="text-muted-foreground">No surplus deliveries right now</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      Check back later to help deliver food to organizations in need
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <div className="grid gap-4">
                  {surplusDeliveries.map((delivery, i) => (
                    <SurplusDeliveryCard 
                      key={delivery.delivery_id} 
                      delivery={delivery} 
                      index={i}
                      onVolunteer={handleVolunteerSurplus}
                    />
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  );
};

// The dropoff direction as a rotating arrow. The server sends the bearing in
// degrees clockwise from north, so the screen never works out which way is
// which - it just points the arrow by that many degrees.
const CompassArrow = ({ bearing, direction }) => (
  <span
    className="inline-flex items-center gap-1"
    data-testid="dropoff-arrow"
    title={`Dropoff is ${COMPASS_WORDS[direction] || direction}`}
  >
    <ArrowUp
      className="w-4 h-4 text-primary"
      style={{ transform: `rotate(${bearing ?? 0}deg)` }}
    />
    <span className="text-xs font-medium">{direction}</span>
  </span>
);

// One job on the board, showing everything the decision needs: how far, which
// way, from which kitchen, what it pays, and what is in the bag.
const OrderCard = ({ order, index, onAccept, onDecline }) => {
  const instruction = INSTRUCTION_LABELS[order.delivery_instruction_type] || INSTRUCTION_LABELS['hand_to_customer'];
  const Icon = instruction.icon;
  // A job nobody has located has no distance to quote, which is not the same as
  // a short one: the card says so instead of inventing a number.
  const measured = typeof order.distance_km === 'number';
  const pay = order.pay_amount ?? ((order.delivery_fee || 0) + (order.tip_amount || 0));
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1 }}
    >
      <Card
        className={`hover:shadow-lg transition-shadow ${order.was_rejected ? 'border-amber-300 dark:border-amber-800' : ''}`}
        data-testid={`order-${order.order_id}`}
      >
        <CardContent className="p-6">
          <div className="flex flex-col gap-4">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="secondary">
                    {order.item_count || order.items?.length || 0} items
                  </Badge>
                  {order.unsealed_drink_count > 0 && (
                    <Badge className="bg-blue-100 text-blue-700">
                      🥤 {order.unsealed_drink_count} unsealed
                      {order.unsealed_drink_count === 1 ? ' drink' : ' drinks'}
                    </Badge>
                  )}
                  {order.unsealed_drink_count === 0 && order.drink_count > 0 && (
                    <Badge variant="outline">
                      🥤 {order.drink_count} sealed
                      {order.drink_count === 1 ? ' drink' : ' drinks'}
                    </Badge>
                  )}
                  {order.requires_cup_holder && (
                    <Badge className="bg-blue-600 text-white">
                      Cup holder needed
                    </Badge>
                  )}
                  {order.was_rejected && (
                    <Badge className="bg-amber-100 text-amber-700">
                      You rejected this
                    </Badge>
                  )}
                  <Badge variant="outline" className="text-xs">
                    <Icon className="w-3 h-3 mr-1" />
                    {instruction.label}
                  </Badge>
                </div>
                <p className="font-semibold text-lg">
                  {order.restaurant_name || 'Restaurant'}
                </p>
                <div className="flex items-center gap-4 text-sm text-muted-foreground flex-wrap">
                  <span className="flex items-center gap-1" data-testid={`eta-${order.order_id}`}>
                    <Clock className="w-4 h-4" />
                    {measured ? `~${order.eta_minutes} min` : 'ETA unknown'}
                  </span>
                  <span className="flex items-center gap-1">
                    <MapPin className="w-4 h-4" />
                    {measured ? `${order.distance_km} km` : 'distance unknown'}
                    {measured && order.dropoff_direction && (
                      <CompassArrow
                        bearing={order.dropoff_bearing}
                        direction={order.dropoff_direction}
                      />
                    )}
                  </span>
                  <span className="text-xs">#{order.order_id.slice(-8)}</span>
                </div>
              </div>
              
              <div className="flex items-center gap-3 flex-wrap justify-end">
                <div className="text-right">
                  <p
                    className="text-2xl font-bold text-green-600 font-mono"
                    data-testid={`pay-${order.order_id}`}
                  >
                    ${pay.toFixed(2)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Pay{order.tip_amount > 0 && ` (incl. $${order.tip_amount.toFixed(2)} tip)`}
                  </p>
                </div>

                {/* Not wired: driver consultation needs a chat backend. Shown
                    because the screen is being built around it. */}
                <Button
                  variant="outline"
                  disabled
                  title="Driver consultation is not built yet - this button is a placeholder."
                  data-testid={`consult-order-${order.order_id}`}
                >
                  <MessageSquare className="w-4 h-4 mr-2" />
                  Consult
                  <span className="ml-2 text-[10px] uppercase tracking-wide">soon</span>
                </Button>

                <Button
                  variant="outline"
                  onClick={() => onDecline(order.order_id)}
                  data-testid={`decline-order-${order.order_id}`}
                >
                  Reject
                </Button>

                {order.requires_cup_holder ? (
                  // The driver may still take it - a bicycle with a handlebar
                  // tray or a backpack holder is a valid setup. Asking first is
                  // the point: the order is accepted knowingly, not by accident.
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button data-testid={`accept-order-${order.order_id}`}>
                        Accept
                        <ArrowRight className="w-4 h-4 ml-2" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Unsealed drinks on this order</AlertDialogTitle>
                        <AlertDialogDescription>
                          {`This order has ${order.unsealed_drink_count} unsealed drink${order.unsealed_drink_count === 1 ? '' : 's'}, and this vehicle has nowhere to stand a cup.`}
                          {' '}Accept only if you are carrying a cup holder or tray.
                          Otherwise reject it and leave it for a driver who is.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => onAccept(order.order_id)}>
                          Accept anyway
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                ) : (
                  <Button
                    onClick={() => onAccept(order.order_id)}
                    data-testid={`accept-order-${order.order_id}`}
                  >
                    Accept
                    <ArrowRight className="w-4 h-4 ml-2" />
                  </Button>
                )}
              </div>
            </div>

            {/* Where the trip starts, and roughly where it ends. The exact
                address is not on offer: it arrives with the job. */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              <div className="p-3 rounded-lg bg-secondary/50">
                <p className="text-xs text-muted-foreground mb-1">📍 Pickup</p>
                <p className="font-medium">{order.restaurant_name || 'Restaurant'}</p>
              </div>
              <div className="p-3 rounded-lg bg-secondary/50">
                <p className="text-xs text-muted-foreground mb-1">
                  🏠 Dropoff {measured && `· ${order.distance_km} km ${order.dropoff_direction || ''}`}
                </p>
                <p className="font-medium">
                  {measured
                    ? `About ${order.distance_km} km to the ${COMPASS_WORDS[order.dropoff_direction] || 'unknown direction'}`
                    : 'Location not on file'}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Exact address comes with the job once you accept it
                </p>
              </div>
            </div>
            
            {/* Delivery Instructions Preview */}
            {order.delivery_instructions && (
              <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 text-sm">
                <p className="text-amber-700 dark:text-amber-300 flex items-center gap-2">
                  <MessageSquare className="w-4 h-4 flex-shrink-0" />
                  <span className="line-clamp-1">"{order.delivery_instructions}"</span>
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

// A claimed volunteer run, from the pickup counter to the organization's door.
// The order card above cannot carry this: a run has no items and no fee, and a
// volunteer may have one alongside a paid order.
const ActiveSurplusRunCard = ({ run, onUpdate, onAbandon }) => {
  const next = {
    assigned: { label: 'I have the food', status: 'picked_up', icon: Package, testId: 'surplus-picked-up' },
    picked_up: { label: 'Start Delivery', status: 'in_transit', icon: Navigation, testId: 'surplus-start-delivery' },
    in_transit: { label: 'Complete Delivery', status: 'delivered', icon: CheckCircle, testId: 'surplus-complete-delivery' },
  }[run.status];
  const NextIcon = next?.icon;

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
      <Card
        className="border-2 border-green-500 bg-green-500/5"
        data-testid={`active-surplus-${run.delivery_id}`}
      >
        <CardHeader>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <CardTitle className="flex items-center gap-2">
              <Heart className="w-5 h-5 text-green-600" />
              Volunteer Run
              <Badge variant="secondary">{run.quantity} portions</Badge>
            </CardTitle>
            <Badge className="bg-green-100 text-green-800">
              {run.status.replace('_', ' ')}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid md:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-secondary">
              <p className="font-medium flex items-center gap-2">
                <Package className="w-4 h-4 text-orange-500" /> Pickup
              </p>
              <p className="text-sm text-muted-foreground">{run.restaurant_name}</p>
              <p className="text-sm">{run.pickup?.address || 'Address unavailable'}</p>
              {(run.pickup?.city || run.pickup?.zip_code) && (
                <p className="text-xs text-muted-foreground">
                  {[run.pickup.city, run.pickup.zip_code].filter(Boolean).join(' ')}
                </p>
              )}
            </div>
            <div className="p-4 rounded-xl bg-secondary">
              <p className="font-medium flex items-center gap-2">
                <MapPin className="w-4 h-4 text-green-500" /> Dropoff
              </p>
              <p className="text-sm text-muted-foreground">{run.org_name}</p>
              <p className="text-sm">{run.dropoff?.address || 'Address unavailable'}</p>
              {(run.dropoff?.city || run.dropoff?.zip_code) && (
                <p className="text-xs text-muted-foreground">
                  {[run.dropoff.city, run.dropoff.zip_code].filter(Boolean).join(' ')}
                </p>
              )}
            </div>
          </div>

          {run.description && (
            <div className="p-3 rounded-lg bg-green-50 dark:bg-green-950/30 text-sm text-green-700 dark:text-green-300">
              {run.description}
            </div>
          )}

          {next && (
            <div className="flex flex-col sm:flex-row gap-3">
              <Button
                onClick={() => onUpdate(run.delivery_id, next.status)}
                className="flex-1 bg-green-600 hover:bg-green-700"
                data-testid={`${next.testId}-${run.delivery_id}`}
              >
                {NextIcon && <NextIcon className="w-4 h-4 mr-2" />}
                {next.label}
              </Button>

              {/* Only before pickup: once the food is in hand there is nothing
                  to return, so the card offers the next step instead. */}
              {run.status === 'assigned' && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="outline"
                      className="sm:flex-1"
                      data-testid={`surplus-abandon-${run.delivery_id}`}
                    >
                      <RotateCcw className="w-4 h-4 mr-2" />
                      Abandon run
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Return this run to the pool?</AlertDialogTitle>
                      <AlertDialogDescription>
                        The food will be offered to another volunteer. Once you
                        have collected it, the run has to be delivered instead.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Keep it</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => onAbandon(run.delivery_id)}
                        data-testid={`confirm-surplus-abandon-${run.delivery_id}`}
                        className="bg-destructive hover:bg-destructive/90"
                      >
                        Return to pool
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

// Surplus Delivery Card for volunteer opportunities
const SurplusDeliveryCard = ({ delivery, index, onVolunteer }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1 }}
    >
      <Card className="hover:shadow-lg transition-shadow border-green-200 dark:border-green-800" data-testid={`surplus-${delivery.delivery_id}`}>
        <CardContent className="p-6">
          <div className="flex flex-col gap-4">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge className="bg-green-100 text-green-700">
                    <Heart className="w-3 h-3 mr-1" />
                    Volunteer
                  </Badge>
                  <Badge variant="secondary">
                    {delivery.quantity} portions
                  </Badge>
                </div>
                <p className="font-semibold">{delivery.restaurant_name}</p>
                <p className="text-sm text-muted-foreground">→ {delivery.org_name}</p>
                <div className="flex items-center gap-4 text-sm text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Clock className="w-4 h-4" />
                    ~{delivery.estimated_time || 20} min
                  </span>
                  {delivery.distance_km && (
                    <span className="flex items-center gap-1">
                      <MapPin className="w-4 h-4" />
                      {delivery.distance_km} km
                    </span>
                  )}
                </div>
              </div>
              
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <p className="text-lg font-bold text-green-600">
                    💚 Volunteer
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Help feed those in need
                  </p>
                </div>
                
                <Button
                  onClick={() => onVolunteer(delivery.delivery_id)}
                  className="bg-green-600 hover:bg-green-700"
                  data-testid={`volunteer-surplus-${delivery.delivery_id}`}
                >
                  <Heart className="w-4 h-4 mr-2" />
                  Volunteer
                </Button>
              </div>
            </div>
            
            {/* Description */}
            {delivery.description && (
              <div className="p-3 rounded-lg bg-green-50 dark:bg-green-950/30 text-sm">
                <p className="text-green-700 dark:text-green-300">
                  {delivery.description}
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default DriverDeliveries;
