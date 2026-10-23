import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import ImageUploadField from '../components/ImageUploadField';
import { imageSrc } from '../lib/images';
import { Switch } from '../components/ui/switch';
import { Badge } from '../components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  Plus, Edit2, Trash2, Store, DollarSign, 
  Image, Tag, Save, Loader2, Heart, CupSoda
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RestaurantMenu = () => {
  const navigate = useNavigate();
  const { token, user } = useAuth();
  const [restaurant, setRestaurant] = useState(null);
  const [menuItems, setMenuItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    price: '',
    category: '',
    image_url: '',
    is_available: true,
    is_drink: false,
    is_sealed: false,
    is_surplus: false,
    surplus_quantity: 0
  });

  useEffect(() => {
    fetchRestaurant();
  }, []);

  const fetchRestaurant = async () => {
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const res = await axios.get(`${API}/restaurants`, { headers, withCredentials: true });
      
      // Find restaurant owned by current user
      const myRestaurant = res.data.find(r => r.user_id === user?.user_id);
      if (myRestaurant) {
        setRestaurant(myRestaurant);
        setMenuItems(myRestaurant.menu || []);
      }
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDialog = (item = null) => {
    if (item) {
      setEditingItem(item);
      setFormData({
        name: item.name,
        description: item.description || '',
        price: item.price.toString(),
        category: item.category || '',
        image_url: item.image_url || '',
        is_available: item.is_available,
        is_drink: item.is_drink || false,
        is_sealed: item.is_sealed || false,
        is_surplus: item.is_surplus || false,
        surplus_quantity: item.surplus_quantity || 0
      });
    } else {
      setEditingItem(null);
      setFormData({
        name: '',
        description: '',
        price: '',
        category: '',
        image_url: '',
        is_available: true,
        is_drink: false,
        is_sealed: false,
        is_surplus: false,
        surplus_quantity: 0
      });
    }
    setDialogOpen(true);
  };

  const handleSaveItem = async () => {
    if (!formData.name || !formData.price) {
      toast.error('Name and price are required');
      return;
    }

    setSaving(true);
    try {
      const newItem = {
        item_id: editingItem?.item_id || `item_${Date.now()}`,
        name: formData.name,
        description: formData.description,
        price: parseFloat(formData.price),
        category: formData.category,
        image_url: formData.image_url,
        is_available: formData.is_available,
        is_drink: formData.is_drink,
        is_sealed: formData.is_drink ? formData.is_sealed : false,
        is_surplus: formData.is_surplus,
        surplus_quantity: formData.is_surplus ? parseInt(formData.surplus_quantity) : 0
      };

      let updatedMenu;
      if (editingItem) {
        updatedMenu = menuItems.map(item => 
          item.item_id === editingItem.item_id ? newItem : item
        );
      } else {
        updatedMenu = [...menuItems, newItem];
      }

      await axios.put(`${API}/restaurants/${restaurant.restaurant_id}/menu`, updatedMenu, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });

      setMenuItems(updatedMenu);
      setDialogOpen(false);
      toast.success(editingItem ? 'Item updated!' : 'Item added!');
    } catch (error) {
      toast.error('Failed to save item');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteItem = async (itemId) => {
    if (!confirm('Delete this item?')) return;

    try {
      const updatedMenu = menuItems.filter(item => item.item_id !== itemId);
      await axios.put(`${API}/restaurants/${restaurant.restaurant_id}/menu`, updatedMenu, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setMenuItems(updatedMenu);
      toast.success('Item deleted');
    } catch (error) {
      toast.error('Failed to delete item');
    }
  };

  const handleToggleAvailability = async (item) => {
    const updatedMenu = menuItems.map(i => 
      i.item_id === item.item_id ? { ...i, is_available: !i.is_available } : i
    );
    
    try {
      await axios.put(`${API}/restaurants/${restaurant.restaurant_id}/menu`, updatedMenu, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setMenuItems(updatedMenu);
    } catch (error) {
      toast.error('Failed to update');
    }
  };

  // Group items by category
  const menuByCategory = menuItems.reduce((acc, item) => {
    const cat = item.category || 'Uncategorized';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {});

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <div className="animate-pulse space-y-4">
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

  if (!restaurant) {
    return (
      <div className="p-6 md:p-8">
        <Card>
          <CardContent className="p-12 text-center">
            <Store className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">You haven't registered a restaurant yet</p>
            <Button className="mt-4" onClick={() => navigate('/restaurant/register')}>
              Register Restaurant
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="restaurant-menu-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Menu Management</h1>
          <p className="text-muted-foreground">{restaurant.name} • {menuItems.length} items</p>
        </div>
        
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={() => handleOpenDialog()} data-testid="add-item-button">
              <Plus className="w-4 h-4 mr-2" />
              Add Item
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>{editingItem ? 'Edit Item' : 'Add New Item'}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="Margherita Pizza"
                  data-testid="item-name-input"
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="Fresh tomatoes, mozzarella, basil..."
                  rows={2}
                />
              </div>
              
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="price">Price *</Label>
                  <div className="relative">
                    <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input
                      id="price"
                      type="number"
                      step="0.01"
                      value={formData.price}
                      onChange={(e) => setFormData(prev => ({ ...prev, price: e.target.value }))}
                      className="pl-9"
                      placeholder="12.99"
                      data-testid="item-price-input"
                    />
                  </div>
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="category">Category</Label>
                  <Select
                    value={formData.category}
                    onValueChange={(value) => setFormData(prev => ({ ...prev, category: value }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Appetizers">Appetizers</SelectItem>
                      <SelectItem value="Main Course">Main Course</SelectItem>
                      <SelectItem value="Sides">Sides</SelectItem>
                      <SelectItem value="Desserts">Desserts</SelectItem>
                      <SelectItem value="Drinks">Drinks</SelectItem>
                      <SelectItem value="Specials">Specials</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              
              <ImageUploadField
                id="item-image"
                testId="item-image"
                label="Item Image"
                value={formData.image_url}
                onChange={(url) => setFormData(prev => ({ ...prev, image_url: url }))}
              />
              
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Available</Label>
                  <p className="text-xs text-muted-foreground">Show on menu</p>
                </div>
                <Switch
                  checked={formData.is_available}
                  onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_available: checked }))}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label className="flex items-center gap-2">
                    <CupSoda className="w-4 h-4 text-sky-500" />
                    Drink
                  </Label>
                  <p className="text-xs text-muted-foreground">Travels separately on delivery</p>
                </div>
                <Switch
                  checked={formData.is_drink}
                  onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_drink: checked }))}
                />
              </div>

              {formData.is_drink && (
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label>Sealed bottle or can</Label>
                    <p className="text-xs text-muted-foreground">
                      Leave off for fountain drinks and open cups, which couriers are told to plan around
                    </p>
                  </div>
                  <Switch
                    checked={formData.is_sealed}
                    onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_sealed: checked }))}
                    data-testid="item-sealed-switch"
                  />
                </div>
              )}
              
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label className="flex items-center gap-2">
                    <Heart className="w-4 h-4 text-pink-500" />
                    Surplus Food
                  </Label>
                  <p className="text-xs text-muted-foreground">Offer at discount for donation</p>
                </div>
                <Switch
                  checked={formData.is_surplus}
                  onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_surplus: checked }))}
                />
              </div>
              
              {formData.is_surplus && (
                <div className="space-y-2">
                  <Label htmlFor="surplus_qty">Surplus Quantity</Label>
                  <Input
                    id="surplus_qty"
                    type="number"
                    value={formData.surplus_quantity}
                    onChange={(e) => setFormData(prev => ({ ...prev, surplus_quantity: e.target.value }))}
                  />
                </div>
              )}
              
              <Button onClick={handleSaveItem} className="w-full" disabled={saving}>
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                ) : (
                  <Save className="w-4 h-4 mr-2" />
                )}
                {editingItem ? 'Update Item' : 'Add Item'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Menu Items */}
      {menuItems.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Store className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">Your menu is empty</p>
            <p className="text-sm text-muted-foreground mt-1">Add items to start receiving orders</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-8">
          {Object.entries(menuByCategory).map(([category, items]) => (
            <div key={category}>
              <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
                <Tag className="w-5 h-5 text-primary" />
                {category}
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {items.map((item, i) => (
                  <motion.div
                    key={item.item_id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                  >
                    <Card className={`${!item.is_available ? 'opacity-60' : ''}`}>
                      <CardContent className="p-4">
                        <div className="flex gap-4">
                          {item.image_url ? (
                            <img
                              src={imageSrc(item.image_url)}
                              alt={item.name}
                              className="w-20 h-20 rounded-lg object-cover"
                            />
                          ) : (
                            <div className="w-20 h-20 rounded-lg bg-secondary flex items-center justify-center">
                              <Image className="w-8 h-8 text-muted-foreground" />
                            </div>
                          )}
                          
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <h3 className="font-semibold truncate">{item.name}</h3>
                                <p className="text-lg font-mono font-bold text-primary">
                                  ${item.price.toFixed(2)}
                                </p>
                              </div>
                              <div className="flex gap-1">
                                {item.is_drink && (
                                  <Badge className="bg-sky-100 text-sky-700">
                                    <CupSoda className="w-3 h-3 mr-1" />
                                    {item.is_sealed ? 'Sealed drink' : 'Drink'}
                                  </Badge>
                                )}
                                {item.is_surplus && (
                                  <Badge className="bg-pink-100 text-pink-700">
                                    <Heart className="w-3 h-3 mr-1" />
                                    Surplus
                                  </Badge>
                                )}
                              </div>
                            </div>
                            
                            <p className="text-sm text-muted-foreground line-clamp-1 mt-1">
                              {item.description}
                            </p>
                            
                            <div className="flex items-center gap-2 mt-3">
                              <Switch
                                checked={item.is_available}
                                onCheckedChange={() => handleToggleAvailability(item)}
                              />
                              <span className="text-xs text-muted-foreground">
                                {item.is_available ? 'Available' : 'Unavailable'}
                              </span>
                              
                              <div className="ml-auto flex gap-1">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => handleOpenDialog(item)}
                                >
                                  <Edit2 className="w-4 h-4" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="text-destructive"
                                  onClick={() => handleDeleteItem(item.item_id)}
                                >
                                  <Trash2 className="w-4 h-4" />
                                </Button>
                              </div>
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </motion.div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default RestaurantMenu;
