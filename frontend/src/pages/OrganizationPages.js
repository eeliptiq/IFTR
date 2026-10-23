import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  Heart, Clock, MapPin, Store, Package, Building2,
  CheckCircle, ArrowRight, Minus, Plus
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// What has happened to the volunteer run carrying a reservation. A reservation
// is not food in hand: the page shows where the run is, not just a tick.
const DELIVERY_LABELS = {
  pending: 'Awaiting volunteer',
  assigned: 'Volunteer on the way',
  picked_up: 'Picked up',
  in_transit: 'On the way',
  delivered: 'Delivered',
  cancelled: 'Cancelled',
};

const OrganizationRequests = () => {
  const { token, user } = useAuth();
  const [organization, setOrganization] = useState(null);
  const [surplusItems, setSurplusItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reserveDialog, setReserveDialog] = useState({ open: false, item: null });
  const [reserveQty, setReserveQty] = useState(1);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const headers = { Authorization: `Bearer ${token}` };
      
      // Get organization
      const orgsRes = await axios.get(`${API}/organizations?verified_only=false`, { headers, withCredentials: true });
      const myOrg = orgsRes.data.find(o => o.user_id === user?.user_id);
      setOrganization(myOrg);
      
      // Get available surplus
      const surplusRes = await axios.get(`${API}/surplus`, { headers, withCredentials: true });
      setSurplusItems(surplusRes.data.filter(s => s.is_available && s.quantity > 0));
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const openReserveDialog = (item) => {
    setReserveDialog({ open: true, item });
    setReserveQty(1);
  };

  const handleReserve = async () => {
    const item = reserveDialog.item;
    if (!item) return;
    
    if (!organization) {
      toast.error('Please register your organization first');
      return;
    }
    
    if (!organization.is_verified) {
      toast.error('Your organization needs to be verified first');
      return;
    }

    try {
      const res = await axios.post(`${API}/surplus/${item.surplus_id}/reserve`, 
        { quantity: reserveQty },
        {
          headers: { Authorization: `Bearer ${token}` },
          withCredentials: true
        }
      );
      toast.success(`Reserved ${res.data.quantity_reserved} portions! A volunteer driver will deliver.`);
      setReserveDialog({ open: false, item: null });
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to reserve');
    }
  };

  const getTimeRemaining = (expiryTime) => {
    const now = new Date();
    const expiry = new Date(expiryTime);
    const diff = expiry - now;
    
    if (diff <= 0) return 'Expired';
    
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    
    if (hours > 0) return `${hours}h ${minutes}m left`;
    return `${minutes}m left`;
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

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="org-requests-page">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <Heart className="w-8 h-8 text-pink-500" />
          Available Food
        </h1>
        <p className="text-muted-foreground">
          Browse and reserve surplus food from local restaurants
        </p>
      </div>

      {/* Verification Notice */}
      {organization && !organization.is_verified && (
        <Card className="border-amber-500/50 bg-amber-500/5">
          <CardContent className="p-4 flex items-center gap-4">
            <Building2 className="w-8 h-8 text-amber-600" />
            <div>
              <p className="font-medium">Verification Pending</p>
              <p className="text-sm text-muted-foreground">
                Your organization is awaiting admin verification. You can browse but not reserve food yet.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Available Surplus */}
      {surplusItems.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Package className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">No surplus food available right now</p>
            <p className="text-sm text-muted-foreground mt-1">
              Check back later — restaurants list surplus food throughout the day
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {surplusItems.map((item, i) => (
            <motion.div
              key={item.surplus_id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
            >
              <Card className="hover:shadow-lg transition-shadow" data-testid={`surplus-${item.surplus_id}`}>
                <CardContent className="p-6">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div className="space-y-3">
                      <div className="flex items-center gap-3">
                        <Badge className="bg-pink-100 text-pink-700">
                          <Clock className="w-3 h-3 mr-1" />
                          {getTimeRemaining(item.expiry_time)}
                        </Badge>
                        <Badge variant="secondary">
                          <Package className="w-3 h-3 mr-1" />
                          {item.quantity} portions
                        </Badge>
                      </div>
                      
                      <div>
                        <p className="font-semibold text-lg">{item.description}</p>
                        <p className="text-sm text-muted-foreground flex items-center gap-1 mt-1">
                          <Store className="w-4 h-4" />
                          {item.restaurant_name || 'Local Restaurant'}
                        </p>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-sm text-muted-foreground">
                          Value: <span className="line-through">${item.original_price.toFixed(2)}</span>
                        </p>
                        <p className="text-2xl font-bold text-green-600 font-mono">
                          {item.discounted_price === 0 ? 'FREE' : `$${item.discounted_price.toFixed(2)}`}
                        </p>
                      </div>
                      
                      <Button
                        onClick={() => openReserveDialog(item)}
                        disabled={!organization?.is_verified}
                        className="bg-pink-600 hover:bg-pink-700"
                        data-testid={`reserve-${item.surplus_id}`}
                      >
                        Reserve
                        <ArrowRight className="w-4 h-4 ml-2" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      {/* Reserve Quantity Dialog */}
      <Dialog open={reserveDialog.open} onOpenChange={(open) => setReserveDialog({ ...reserveDialog, open })}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Reserve Surplus Food</DialogTitle>
          </DialogHeader>
          {reserveDialog.item && (
            <div className="space-y-6 mt-4">
              <div className="p-4 rounded-xl bg-secondary/50">
                <p className="font-semibold">{reserveDialog.item.description}</p>
                <p className="text-sm text-muted-foreground mt-1">
                  From: {reserveDialog.item.restaurant_name || 'Local Restaurant'}
                </p>
                <p className="text-sm text-muted-foreground">
                  Available: {reserveDialog.item.quantity} portions
                </p>
              </div>

              <div className="space-y-3">
                <label className="text-sm font-medium">How many portions do you need?</label>
                <div className="flex items-center justify-center gap-4">
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setReserveQty(Math.max(1, reserveQty - 1))}
                    disabled={reserveQty <= 1}
                  >
                    <Minus className="w-4 h-4" />
                  </Button>
                  <span className="text-3xl font-bold w-16 text-center">{reserveQty}</span>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setReserveQty(Math.min(reserveDialog.item.quantity, reserveQty + 1))}
                    disabled={reserveQty >= reserveDialog.item.quantity}
                  >
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
                <p className="text-center text-sm text-muted-foreground">
                  {reserveDialog.item.quantity - reserveQty} will remain for others
                </p>
              </div>

              <div className="flex gap-3">
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={() => setReserveDialog({ open: false, item: null })}
                >
                  Cancel
                </Button>
                <Button
                  className="flex-1 bg-pink-600 hover:bg-pink-700"
                  onClick={handleReserve}
                >
                  Reserve {reserveQty} portion{reserveQty > 1 ? 's' : ''}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

const OrganizationReceived = () => {
  const { token, user } = useAuth();
  const [organization, setOrganization] = useState(null);
  const [receivedItems, setReceivedItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const headers = { Authorization: `Bearer ${token}` };
      
      // Get organization
      const orgsRes = await axios.get(`${API}/organizations?verified_only=false`, { headers, withCredentials: true });
      const myOrg = orgsRes.data.find(o => o.user_id === user?.user_id);
      setOrganization(myOrg);
      
      if (myOrg) {
        // This organization's own reservations. The listing's quantity is what
        // is left on the shelf, so it cannot say how much this organization
        // booked - especially when the listing was split with another one.
        const surplusRes = await axios.get(`${API}/surplus/reservations`, { headers, withCredentials: true });
        setReceivedItems(surplusRes.data);
      }
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
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

  const totalPortions = receivedItems.reduce((sum, item) => sum + item.quantity, 0);
  const totalValue = receivedItems.reduce((sum, item) => sum + item.original_price, 0);

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="org-received-page">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <CheckCircle className="w-8 h-8 text-green-500" />
          Received Food
        </h1>
        <p className="text-muted-foreground">
          Surplus food your organization has reserved, and where each run stands
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-green-600">{receivedItems.length}</p>
            <p className="text-sm text-muted-foreground">Reservations</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-pink-600">{totalPortions}</p>
            <p className="text-sm text-muted-foreground">Portions Reserved</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold font-mono">${totalValue.toFixed(0)}</p>
            <p className="text-sm text-muted-foreground">Value Reserved</p>
          </CardContent>
        </Card>
      </div>

      {/* Received Items */}
      {receivedItems.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Heart className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">No donations received yet</p>
            <Button className="mt-4" onClick={() => window.location.href = '/organization/requests'}>
              Browse Available Food
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {receivedItems.map((item, i) => (
            <motion.div
              key={item.surplus_id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
            >
              <Card className="border-green-500/30 bg-green-500/5">
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div className="space-y-2">
                      <div className="flex items-center gap-3">
                        <Badge className={item.delivery_status === 'delivered'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-amber-100 text-amber-800'
                        }>
                          {item.delivery_status === 'delivered' ? (
                            <CheckCircle className="w-3 h-3 mr-1" />
                          ) : (
                            <Clock className="w-3 h-3 mr-1" />
                          )}
                          {DELIVERY_LABELS[item.delivery_status] || 'Reserved'}
                        </Badge>
                        <Badge variant="secondary">
                          {item.quantity} portions
                        </Badge>
                      </div>
                      <p className="font-medium">{item.description}</p>
                      <p className="text-sm text-muted-foreground">
                        From: {item.restaurant_name || 'Local Restaurant'}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-muted-foreground">Value</p>
                      <p className="text-xl font-bold text-green-600 font-mono">
                        ${item.original_price.toFixed(2)}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
};

export { OrganizationRequests, OrganizationReceived };
