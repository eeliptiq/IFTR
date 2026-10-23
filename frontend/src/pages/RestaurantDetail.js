import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { imageSrc } from '../lib/images';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '../components/ui/sheet';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  ArrowLeft, Star, Clock, MapPin, Plus, Minus, 
  ShoppingCart, Trash2, Heart, DoorOpen, User, Building, MessageSquare, DollarSign
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const DELIVERY_INSTRUCTIONS = [
  { value: 'hand_to_customer', label: 'Hand it to me', icon: User, description: 'Driver will wait for you' },
  { value: 'leave_at_door', label: 'Leave at door', icon: DoorOpen, description: 'Driver will leave order at your door' },
  { value: 'meet_outside', label: 'Meet outside', icon: MapPin, description: 'Meet driver outside your building' },
  { value: 'meet_in_lobby', label: 'Meet in lobby', icon: Building, description: 'Meet driver in the lobby' },
];

const TIP_PRESETS = [0, 2, 3, 5, 10];

const DELIVERY_SPEEDS = [
  { value: 'priority', label: 'Priority', desc: '~30% faster', feeMultiplier: 1.5, icon: '🚀' },
  { value: 'standard', label: 'Standard', desc: 'Normal delivery', feeMultiplier: 1.0, icon: '📦' },
  { value: 'economy', label: 'Economy', desc: 'Save 50% on fee', feeMultiplier: 0.5, icon: '💰' },
];

const RestaurantDetail = () => {
  const { restaurantId } = useParams();
  const navigate = useNavigate();
  const { token, user } = useAuth();
  const [restaurant, setRestaurant] = useState(null);
  const [loading, setLoading] = useState(true);
  const [cart, setCart] = useState([]);
  const [cartOpen, setCartOpen] = useState(false);
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [deliveryOptions, setDeliveryOptions] = useState({
    instruction_type: 'hand_to_customer',
    instructions: '',
    address: '',
    tip_amount: 3,  // Default $3 tip
    delivery_speed: 'standard',
    scheduled_for: null  // null = ASAP
  });
  const [customTip, setCustomTip] = useState('');
  const [showScheduler, setShowScheduler] = useState(false);

  useEffect(() => {
    fetchRestaurant();
  }, [restaurantId]);

  const fetchRestaurant = async () => {
    try {
      const res = await axios.get(`${API}/restaurants/${restaurantId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        withCredentials: true
      });
      setRestaurant(res.data);
    } catch (error) {
      toast.error('Restaurant not found');
      navigate('/restaurants');
    } finally {
      setLoading(false);
    }
  };

  const addToCart = (item) => {
    setCart(prev => {
      const existing = prev.find(i => i.item_id === item.item_id);
      if (existing) {
        return prev.map(i => 
          i.item_id === item.item_id 
            ? { ...i, quantity: i.quantity + 1 }
            : i
        );
      }
      return [...prev, { ...item, quantity: 1 }];
    });
    toast.success(`Added ${item.name} to cart`);
  };

  const updateQuantity = (itemId, delta) => {
    setCart(prev => {
      return prev.map(item => {
        if (item.item_id === itemId) {
          const newQty = item.quantity + delta;
          if (newQty <= 0) return null;
          return { ...item, quantity: newQty };
        }
        return item;
      }).filter(Boolean);
    });
  };

  const cartTotal = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);
  const cartCount = cart.reduce((sum, item) => sum + item.quantity, 0);
  const baseDeliveryFee = cartTotal < 30 ? 2.99 : 0;
  
  // Apply speed multiplier to delivery fee
  const speedOption = DELIVERY_SPEEDS.find(s => s.value === deliveryOptions.delivery_speed) || DELIVERY_SPEEDS[1];
  const deliveryFee = Math.round(baseDeliveryFee * speedOption.feeMultiplier * 100) / 100;
  
  const tipAmount = deliveryOptions.tip_amount || 0;
  const orderTotal = cartTotal + deliveryFee + tipAmount;

  const openCheckout = () => {
    if (!user) {
      toast.error('Please sign in to place an order');
      navigate('/auth');
      return;
    }
    setCheckoutOpen(true);
  };

  const handleTipSelect = (amount) => {
    setDeliveryOptions({...deliveryOptions, tip_amount: amount});
    setCustomTip('');
  };

  const handleCustomTip = (value) => {
    const amount = parseFloat(value) || 0;
    setCustomTip(value);
    setDeliveryOptions({...deliveryOptions, tip_amount: amount});
  };

  const handleCheckout = async () => {
    if (!deliveryOptions.address) {
      toast.error('Please enter a delivery address');
      return;
    }

    // Create order with delivery instructions, tip, speed, and schedule
    const orderData = {
      restaurant_id: restaurantId,
      items: cart.map(item => ({
        item_id: item.item_id,
        name: item.name,
        quantity: item.quantity,
        price: item.price,
        is_surplus: item.is_surplus || false
      })),
      delivery_lat: 40.7128, // Demo coordinates - would use geocoding in production
      delivery_lng: -74.006,
      delivery_address: deliveryOptions.address,
      delivery_instruction_type: deliveryOptions.instruction_type,
      delivery_instructions: deliveryOptions.instructions,
      tip_amount: tipAmount,
      delivery_speed: deliveryOptions.delivery_speed,
      scheduled_for: deliveryOptions.scheduled_for || null
    };

    let order;
    try {
      order = (await axios.post(`${API}/orders`, orderData, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      })).data;
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to create order');
      return;
    }

    // The order exists from here on, so nothing below may report a failure as
    // if it did not: a customer told "failed" orders again and pays twice. If
    // Checkout cannot be reached the order stands, unpaid, and the message says
    // exactly that instead of claiming a payment happened.
    try {
      const checkoutRes = await axios.post(`${API}/payments/checkout`, {
        order_id: order.order_id,
        origin_url: window.location.origin
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      if (checkoutRes.data?.url) {
        window.location.href = checkoutRes.data.url;
        return;
      }
      toast.warning('Order placed, but the payment page could not be opened. Nothing was charged.');
    } catch (paymentError) {
      const httpStatus = paymentError?.response?.status;
      const detail = paymentError?.response?.data?.detail;
      if (httpStatus === 503) {
        // No Stripe key on this deployment. The order is real and the kitchen
        // will see it; saying "paid" would be a lie.
        toast.warning('Order placed. Payments are not set up on this server, so nothing was charged.');
      } else {
        console.warn('Payment hand-off failed:', detail || paymentError?.message);
        toast.error(detail || 'Order placed, but the payment page could not be opened. Nothing was charged.');
      }
    }

    navigate(`/orders/${order.order_id}`);
  };

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <div className="animate-pulse space-y-6">
          <div className="h-64 bg-muted rounded-2xl" />
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-32 bg-muted rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!restaurant) return null;

  // Group menu items by category
  const menuByCategory = restaurant.menu?.reduce((acc, item) => {
    const cat = item.category || 'Other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {}) || {};

  return (
    <div className="pb-24" data-testid="restaurant-detail">
      {/* Header Image */}
      <div className="relative h-64 bg-secondary">
        {restaurant.image_url ? (
          <img
            src={imageSrc(restaurant.image_url)}
            alt={restaurant.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-primary/20 to-primary/5" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-background to-transparent" />
        
        {/* Back Button */}
        <Button
          variant="ghost"
          size="icon"
          className="absolute top-4 left-4 bg-background/80 backdrop-blur"
          onClick={() => navigate('/restaurants')}
          data-testid="back-button"
        >
          <ArrowLeft className="w-5 h-5" />
        </Button>
      </div>

      {/* Restaurant Info */}
      <div className="px-6 md:px-8 -mt-16 relative">
        <Card className="p-6">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold">{restaurant.name}</h1>
              <p className="text-muted-foreground mt-1">{restaurant.description}</p>
              <div className="flex items-center gap-4 mt-3">
                {restaurant.cuisine_type && (
                  <Badge variant="secondary">{restaurant.cuisine_type}</Badge>
                )}
                {restaurant.rating > 0 && (
                  <div className="flex items-center gap-1">
                    <Star className="w-4 h-4 text-amber-500 fill-amber-500" />
                    <span className="font-semibold">{restaurant.rating.toFixed(1)}</span>
                    <span className="text-muted-foreground">({restaurant.total_reviews} reviews)</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Menu */}
      <div className="px-6 md:px-8 mt-8 space-y-8">
        {Object.keys(menuByCategory).length === 0 ? (
          <Card>
            <CardContent className="p-12 text-center">
              <p className="text-muted-foreground">No menu items available</p>
            </CardContent>
          </Card>
        ) : (
          Object.entries(menuByCategory).map(([category, items]) => (
            <div key={category}>
              <h2 className="text-xl font-bold mb-4">{category}</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {items.map((item, i) => (
                  <motion.div
                    key={item.item_id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                  >
                    <Card className="menu-item-card">
                      {item.image_url && (
                        <img
                          src={imageSrc(item.image_url)}
                          alt={item.name}
                          className="w-24 h-24 rounded-lg object-cover"
                        />
                      )}
                      <div className="flex-1">
                        <div className="flex items-start justify-between">
                          <div>
                            <h3 className="font-semibold">{item.name}</h3>
                            {item.is_surplus && (
                              <Badge variant="secondary" className="mt-1 bg-pink-100 text-pink-700">
                                <Heart className="w-3 h-3 mr-1" />
                                Surplus
                              </Badge>
                            )}
                          </div>
                          <span className="font-mono font-bold text-primary">
                            ${item.price.toFixed(2)}
                          </span>
                        </div>
                        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                          {item.description}
                        </p>
                        <Button
                          size="sm"
                          className="mt-3"
                          onClick={() => addToCart(item)}
                          disabled={!item.is_available}
                          data-testid={`add-to-cart-${item.item_id}`}
                        >
                          <Plus className="w-4 h-4 mr-1" />
                          Add
                        </Button>
                      </div>
                    </Card>
                  </motion.div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Cart Button */}
      {cartCount > 0 && (
        <div className="fixed bottom-0 left-0 right-0 p-4 bg-background border-t border-border md:left-64">
          <Sheet open={cartOpen} onOpenChange={setCartOpen}>
            <SheetTrigger asChild>
              <Button className="w-full h-14 text-lg" data-testid="view-cart-button">
                <ShoppingCart className="w-5 h-5 mr-2" />
                View Cart ({cartCount}) • ${cartTotal.toFixed(2)}
              </Button>
            </SheetTrigger>
            <SheetContent className="w-full sm:max-w-lg">
              <SheetHeader>
                <SheetTitle>Your Cart</SheetTitle>
              </SheetHeader>
              
              <div className="mt-6 space-y-4 flex-1 overflow-y-auto">
                {cart.map(item => (
                  <div key={item.item_id} className="flex items-center gap-4 p-4 bg-secondary/50 rounded-xl">
                    <div className="flex-1">
                      <p className="font-semibold">{item.name}</p>
                      <p className="text-sm text-muted-foreground">
                        ${item.price.toFixed(2)} each
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        size="icon"
                        variant="outline"
                        onClick={() => updateQuantity(item.item_id, -1)}
                      >
                        <Minus className="w-4 h-4" />
                      </Button>
                      <span className="w-8 text-center font-semibold">{item.quantity}</span>
                      <Button
                        size="icon"
                        variant="outline"
                        onClick={() => updateQuantity(item.item_id, 1)}
                      >
                        <Plus className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-6 pt-6 border-t border-border space-y-4">
                <div className="flex justify-between text-lg font-semibold">
                  <span>Total</span>
                  <span className="font-mono">${cartTotal.toFixed(2)}</span>
                </div>
                <Button 
                  className="w-full h-12" 
                  onClick={openCheckout}
                  data-testid="checkout-button"
                >
                  Continue to Checkout
                </Button>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      )}

      {/* Checkout Dialog with Delivery Instructions */}
      <Dialog open={checkoutOpen} onOpenChange={setCheckoutOpen}>
        <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Delivery Details</DialogTitle>
          </DialogHeader>
          
          <div className="space-y-6 mt-4">
            {/* Delivery Speed Selection */}
            <div className="space-y-3">
              <Label>Delivery Speed</Label>
              <div className="grid grid-cols-3 gap-2">
                {DELIVERY_SPEEDS.map((speed) => (
                  <button
                    key={speed.value}
                    type="button"
                    onClick={() => setDeliveryOptions({...deliveryOptions, delivery_speed: speed.value})}
                    className={`p-3 rounded-xl border-2 text-center transition-all ${
                      deliveryOptions.delivery_speed === speed.value
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/50'
                    }`}
                    data-testid={`speed-${speed.value}`}
                  >
                    <span className="text-2xl">{speed.icon}</span>
                    <p className="font-medium text-sm mt-1">{speed.label}</p>
                    <p className="text-xs text-muted-foreground">{speed.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Schedule or ASAP */}
            <div className="space-y-3">
              <Label>When do you want it?</Label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowScheduler(false);
                    setDeliveryOptions({...deliveryOptions, scheduled_for: null});
                  }}
                  className={`flex-1 p-3 rounded-xl border-2 text-center transition-all ${
                    !showScheduler ? 'border-primary bg-primary/5' : 'border-border'
                  }`}
                >
                  <Clock className="w-5 h-5 mx-auto mb-1" />
                  <p className="font-medium text-sm">ASAP</p>
                </button>
                <button
                  type="button"
                  onClick={() => setShowScheduler(true)}
                  className={`flex-1 p-3 rounded-xl border-2 text-center transition-all ${
                    showScheduler ? 'border-primary bg-primary/5' : 'border-border'
                  }`}
                >
                  <MapPin className="w-5 h-5 mx-auto mb-1" />
                  <p className="font-medium text-sm">Schedule</p>
                </button>
              </div>
              {showScheduler && (
                <Input
                  type="datetime-local"
                  min={new Date().toISOString().slice(0, 16)}
                  value={deliveryOptions.scheduled_for || ''}
                  onChange={(e) => setDeliveryOptions({...deliveryOptions, scheduled_for: e.target.value})}
                  className="mt-2"
                  data-testid="schedule-input"
                />
              )}
            </div>

            {/* Delivery Address */}
            <div className="space-y-2">
              <Label htmlFor="address">Delivery Address *</Label>
              <Input
                id="address"
                value={deliveryOptions.address}
                onChange={(e) => setDeliveryOptions({...deliveryOptions, address: e.target.value})}
                placeholder="123 Main St, Apt 4B"
                data-testid="delivery-address-input"
              />
            </div>

            {/* Delivery Instructions Type */}
            <div className="space-y-3">
              <Label>Delivery Instructions</Label>
              <div className="grid grid-cols-2 gap-3">
                {DELIVERY_INSTRUCTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setDeliveryOptions({...deliveryOptions, instruction_type: option.value})}
                    className={`p-4 rounded-xl border-2 text-left transition-all ${
                      deliveryOptions.instruction_type === option.value
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/50'
                    }`}
                    data-testid={`delivery-option-${option.value}`}
                  >
                    <option.icon className={`w-5 h-5 mb-2 ${
                      deliveryOptions.instruction_type === option.value ? 'text-primary' : 'text-muted-foreground'
                    }`} />
                    <p className="font-medium text-sm">{option.label}</p>
                    <p className="text-xs text-muted-foreground">{option.description}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Additional Instructions */}
            <div className="space-y-2">
              <Label htmlFor="instructions" className="flex items-center gap-2">
                <MessageSquare className="w-4 h-4" />
                Additional Notes (optional)
              </Label>
              <Textarea
                id="instructions"
                value={deliveryOptions.instructions}
                onChange={(e) => setDeliveryOptions({...deliveryOptions, instructions: e.target.value})}
                placeholder="Gate code, building color, landmarks, allergies..."
                rows={3}
                data-testid="delivery-notes-input"
              />
            </div>

            {/* Tip Section */}
            <div className="space-y-3">
              <Label className="flex items-center gap-2">
                <DollarSign className="w-4 h-4" />
                Add a tip for your driver
              </Label>
              <div className="grid grid-cols-5 gap-2">
                {TIP_PRESETS.map((amount) => (
                  <button
                    key={amount}
                    type="button"
                    onClick={() => handleTipSelect(amount)}
                    className={`py-3 px-2 rounded-xl border-2 font-semibold transition-all ${
                      deliveryOptions.tip_amount === amount && !customTip
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border hover:border-primary/50'
                    }`}
                    data-testid={`tip-${amount}`}
                  >
                    {amount === 0 ? 'No tip' : `$${amount}`}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Custom:</span>
                <div className="relative flex-1">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">$</span>
                  <Input
                    type="number"
                    min="0"
                    step="0.5"
                    value={customTip}
                    onChange={(e) => handleCustomTip(e.target.value)}
                    placeholder="Other amount"
                    className="pl-7"
                    data-testid="custom-tip-input"
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                💚 100% of your tip goes directly to your driver. Tips cannot be reduced after ordering.
              </p>
            </div>

            {/* Order Summary */}
            <div className="p-4 rounded-xl bg-secondary/50 space-y-2">
              <div className="flex justify-between text-sm">
                <span>Subtotal</span>
                <span>${cartTotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span>Delivery Fee</span>
                <span>{deliveryFee === 0 ? 'FREE' : `$${deliveryFee.toFixed(2)}`}</span>
              </div>
              {tipAmount > 0 && (
                <div className="flex justify-between text-sm text-green-600">
                  <span>Driver Tip</span>
                  <span>${tipAmount.toFixed(2)}</span>
                </div>
              )}
              <div className="flex justify-between font-bold text-lg pt-2 border-t border-border">
                <span>Total</span>
                <span className="font-mono">${orderTotal.toFixed(2)}</span>
              </div>
            </div>

            {/* Place Order Button */}
            <Button 
              className="w-full h-12" 
              onClick={handleCheckout}
              data-testid="place-order-button"
            >
              Place Order & Pay
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default RestaurantDetail;
