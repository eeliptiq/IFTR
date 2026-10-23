import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  Heart, Plus, Clock, MapPin, Store, Package,
  DollarSign, Loader2, CheckCircle
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RestaurantSurplus = () => {
  const { token, user } = useAuth();
  const [restaurant, setRestaurant] = useState(null);
  const [surplusItems, setSurplusItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formData, setFormData] = useState({
    description: '',
    quantity: '1',
    original_price: '',
    discounted_price: '0',
    expiry_hours: '4'
  });

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const headers = { Authorization: `Bearer ${token}` };
      
      // Get restaurant
      const restRes = await axios.get(`${API}/restaurants`, { headers, withCredentials: true });
      const myRestaurant = restRes.data.find(r => r.user_id === user?.user_id);
      setRestaurant(myRestaurant);
      
      // Get surplus items
      const surplusRes = await axios.get(`${API}/surplus`, { headers, withCredentials: true });
      const mySurplus = myRestaurant 
        ? surplusRes.data.filter(s => s.restaurant_id === myRestaurant.restaurant_id)
        : [];
      setSurplusItems(mySurplus);
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateSurplus = async () => {
    if (!formData.description || !formData.original_price) {
      toast.error('Description and original price are required');
      return;
    }

    setSaving(true);
    try {
      await axios.post(`${API}/surplus`, {
        description: formData.description,
        quantity: parseInt(formData.quantity),
        original_price: parseFloat(formData.original_price),
        discounted_price: parseFloat(formData.discounted_price) || 0,
        expiry_hours: parseInt(formData.expiry_hours)
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      
      toast.success('Surplus food listed!');
      setDialogOpen(false);
      setFormData({
        description: '',
        quantity: '1',
        original_price: '',
        discounted_price: '0',
        expiry_hours: '4'
      });
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to list surplus');
    } finally {
      setSaving(false);
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
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="grid gap-4">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-32 bg-muted rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!restaurant) {
    return (
      <div className="p-6 md:p-8">
        <Card>
          <CardContent className="p-12 text-center">
            <Store className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">Register a restaurant first</p>
            <Button className="mt-4" onClick={() => window.location.href = '/restaurant/register'}>
              Register Restaurant
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="restaurant-surplus-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <Heart className="w-8 h-8 text-pink-500" />
            Surplus Food
          </h1>
          <p className="text-muted-foreground">
            List excess food for donation or discounted sale
          </p>
        </div>
        
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button className="bg-pink-600 hover:bg-pink-700" data-testid="list-surplus-button">
              <Plus className="w-4 h-4 mr-2" />
              List Surplus Food
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>List Surplus Food</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label>Description *</Label>
                <Textarea
                  value={formData.description}
                  onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="10 portions of pasta, 5 salads, assorted desserts..."
                  rows={3}
                  data-testid="surplus-description"
                />
              </div>
              
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Quantity (portions)</Label>
                  <Input
                    type="number"
                    value={formData.quantity}
                    onChange={(e) => setFormData(prev => ({ ...prev, quantity: e.target.value }))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Expires in (hours)</Label>
                  <Input
                    type="number"
                    value={formData.expiry_hours}
                    onChange={(e) => setFormData(prev => ({ ...prev, expiry_hours: e.target.value }))}
                  />
                </div>
              </div>
              
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Original Value *</Label>
                  <div className="relative">
                    <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input
                      type="number"
                      step="0.01"
                      value={formData.original_price}
                      onChange={(e) => setFormData(prev => ({ ...prev, original_price: e.target.value }))}
                      className="pl-9"
                      placeholder="50.00"
                      data-testid="surplus-price"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Asking Price</Label>
                  <div className="relative">
                    <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input
                      type="number"
                      step="0.01"
                      value={formData.discounted_price}
                      onChange={(e) => setFormData(prev => ({ ...prev, discounted_price: e.target.value }))}
                      className="pl-9"
                      placeholder="0 for free"
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">Set to 0 for free donation</p>
                </div>
              </div>
              
              <Button onClick={handleCreateSurplus} className="w-full bg-pink-600 hover:bg-pink-700" disabled={saving}>
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Heart className="w-4 h-4 mr-2" />}
                List for Donation
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Impact Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-pink-600">{surplusItems.length}</p>
            <p className="text-sm text-muted-foreground">Active Listings</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-green-600">
              {surplusItems.reduce((sum, s) => sum + s.quantity, 0)}
            </p>
            <p className="text-sm text-muted-foreground">Portions Available</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold font-mono">
              ${surplusItems.reduce((sum, s) => sum + s.original_price, 0).toFixed(0)}
            </p>
            <p className="text-sm text-muted-foreground">Value Listed</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-amber-600">
              {surplusItems.filter(s => s.reserved_by_org_id).length}
            </p>
            <p className="text-sm text-muted-foreground">Reserved</p>
          </CardContent>
        </Card>
      </div>

      {/* Surplus Listings */}
      {surplusItems.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Heart className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">No surplus food listed</p>
            <p className="text-sm text-muted-foreground mt-1">
              Help reduce waste by listing excess food
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
              <Card className={item.reserved_by_org_id ? 'border-green-500/50 bg-green-500/5' : ''}>
                <CardContent className="p-6">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div className="space-y-2">
                      <div className="flex items-center gap-3">
                        <Badge className={item.reserved_by_org_id 
                          ? 'bg-green-100 text-green-800' 
                          : 'bg-pink-100 text-pink-700'
                        }>
                          {item.reserved_by_org_id ? (
                            <>
                              <CheckCircle className="w-3 h-3 mr-1" />
                              Reserved
                            </>
                          ) : (
                            <>
                              <Clock className="w-3 h-3 mr-1" />
                              {getTimeRemaining(item.expiry_time)}
                            </>
                          )}
                        </Badge>
                        <Badge variant="secondary">
                          <Package className="w-3 h-3 mr-1" />
                          {item.quantity} portions
                        </Badge>
                      </div>
                      <p className="font-medium">{item.description}</p>
                    </div>
                    
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-sm text-muted-foreground line-through">
                          ${item.original_price.toFixed(2)}
                        </p>
                        <p className="text-2xl font-bold text-pink-600 font-mono">
                          {item.discounted_price === 0 ? 'FREE' : `$${item.discounted_price.toFixed(2)}`}
                        </p>
                      </div>
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

export default RestaurantSurplus;
