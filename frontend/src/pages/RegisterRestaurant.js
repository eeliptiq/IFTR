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
  Store, MapPin, UtensilsCrossed, Image, Loader2, 
  CheckCircle, ArrowRight
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RegisterRestaurant = () => {
  const { token, user, updateProfile } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [existingRestaurant, setExistingRestaurant] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    cuisine_type: '',
    image_url: '',
    lat: '',
    lng: '',
    address: '',
    city: '',
    zip_code: ''
  });

  useEffect(() => {
    checkExistingRestaurant();
  }, []);

  const checkExistingRestaurant = async () => {
    try {
      const res = await axios.get(`${API}/restaurants`, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      const myRestaurant = res.data.find(r => r.user_id === user?.user_id);
      if (myRestaurant) {
        setExistingRestaurant(myRestaurant);
      }
    } catch (error) {
      console.error('Check error:', error);
    }
  };

  const handleGetLocation = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setFormData(prev => ({
            ...prev,
            lat: position.coords.latitude.toFixed(6),
            lng: position.coords.longitude.toFixed(6)
          }));
          toast.success('Location captured!');
        },
        () => toast.error('Could not get location')
      );
    }
  };

  const handleSubmit = async () => {
    if (!formData.name || !formData.lat || !formData.lng) {
      toast.error('Name and location are required');
      return;
    }

    setLoading(true);
    try {
      await axios.post(`${API}/restaurants`, {
        name: formData.name,
        description: formData.description,
        cuisine_type: formData.cuisine_type,
        image_url: formData.image_url,
        lat: parseFloat(formData.lat),
        lng: parseFloat(formData.lng),
        address: formData.address,
        city: formData.city,
        zip_code: formData.zip_code
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });

      toast.success('Restaurant registered successfully!');
      setStep(3); // Success step
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  // If already has restaurant, show it
  if (existingRestaurant) {
    return (
      <div className="p-6 md:p-8 max-w-2xl mx-auto">
        <Card className="border-green-500/50 bg-green-500/5">
          <CardContent className="p-8 text-center">
            <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
            <h2 className="text-2xl font-bold mb-2">Restaurant Already Registered</h2>
            <p className="text-muted-foreground mb-6">
              You've already registered <strong>{existingRestaurant.name}</strong>
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <Button onClick={() => navigate('/restaurant/menu')}>
                Manage Menu
              </Button>
              <Button variant="outline" onClick={() => navigate('/restaurant/orders')}>
                View Orders
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-2xl mx-auto" data-testid="register-restaurant-page">
      {/* Progress Steps */}
      <div className="flex items-center justify-center mb-8">
        {[1, 2, 3].map((s) => (
          <React.Fragment key={s}>
            <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold ${
              step >= s ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
            }`}>
              {step > s ? <CheckCircle className="w-5 h-5" /> : s}
            </div>
            {s < 3 && (
              <div className={`w-16 h-1 mx-2 ${step > s ? 'bg-primary' : 'bg-muted'}`} />
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Step 1: Basic Info */}
      {step === 1 && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
        >
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <Store className="w-6 h-6 text-primary" />
                Restaurant Details
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="name">Restaurant Name *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="Joe's Pizza"
                  data-testid="restaurant-name-input"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="Tell customers what makes your restaurant special..."
                  rows={3}
                />
              </div>

              <div className="space-y-2">
                <Label>Cuisine Type</Label>
                <Select
                  value={formData.cuisine_type}
                  onValueChange={(value) => setFormData(prev => ({ ...prev, cuisine_type: value }))}
                >
                  <SelectTrigger data-testid="cuisine-select">
                    <SelectValue placeholder="Select cuisine..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="american">American</SelectItem>
                    <SelectItem value="italian">Italian</SelectItem>
                    <SelectItem value="mexican">Mexican</SelectItem>
                    <SelectItem value="chinese">Chinese</SelectItem>
                    <SelectItem value="japanese">Japanese</SelectItem>
                    <SelectItem value="indian">Indian</SelectItem>
                    <SelectItem value="thai">Thai</SelectItem>
                    <SelectItem value="mediterranean">Mediterranean</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <ImageUploadField
                id="image"
                testId="cover-image"
                label="Cover Image"
                value={formData.image_url}
                onChange={(url) => setFormData(prev => ({ ...prev, image_url: url }))}
                helpText="Upload a photo of your restaurant, or paste a link to one."
              />

              <Button 
                onClick={() => setStep(2)} 
                className="w-full"
                disabled={!formData.name}
                data-testid="next-step-button"
              >
                Next: Location
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Step 2: Location */}
      {step === 2 && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
        >
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <MapPin className="w-6 h-6 text-primary" />
                Location Details
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <Button
                variant="outline"
                onClick={handleGetLocation}
                className="w-full"
                data-testid="get-location-button"
              >
                <MapPin className="w-4 h-4 mr-2" />
                Use My Current Location
              </Button>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="lat">Latitude *</Label>
                  <Input
                    id="lat"
                    value={formData.lat}
                    onChange={(e) => setFormData(prev => ({ ...prev, lat: e.target.value }))}
                    placeholder="40.7128"
                    data-testid="lat-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="lng">Longitude *</Label>
                  <Input
                    id="lng"
                    value={formData.lng}
                    onChange={(e) => setFormData(prev => ({ ...prev, lng: e.target.value }))}
                    placeholder="-74.0060"
                    data-testid="lng-input"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="address">Street Address</Label>
                <Input
                  id="address"
                  value={formData.address}
                  onChange={(e) => setFormData(prev => ({ ...prev, address: e.target.value }))}
                  placeholder="123 Main Street"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="city">City</Label>
                  <Input
                    id="city"
                    value={formData.city}
                    onChange={(e) => setFormData(prev => ({ ...prev, city: e.target.value }))}
                    placeholder="New York"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="zip">ZIP Code</Label>
                  <Input
                    id="zip"
                    value={formData.zip_code}
                    onChange={(e) => setFormData(prev => ({ ...prev, zip_code: e.target.value }))}
                    placeholder="10001"
                  />
                </div>
              </div>

              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <span className="text-green-500">🔒</span>
                Your exact location is encrypted using AES-256
              </p>

              <div className="flex gap-4">
                <Button variant="outline" onClick={() => setStep(1)} className="flex-1">
                  Back
                </Button>
                <Button 
                  onClick={handleSubmit} 
                  className="flex-1"
                  disabled={loading || !formData.lat || !formData.lng}
                  data-testid="register-button"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  ) : (
                    <Store className="w-4 h-4 mr-2" />
                  )}
                  Register Restaurant
                </Button>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Step 3: Success */}
      {step === 3 && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <Card className="border-green-500/50 bg-green-500/5">
            <CardContent className="p-8 text-center">
              <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
              <h2 className="text-2xl font-bold mb-2">Welcome to SharePlate!</h2>
              <p className="text-muted-foreground mb-6">
                Your restaurant <strong>{formData.name}</strong> is now registered.
                Start adding menu items to receive orders!
              </p>
              <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <Button onClick={() => navigate('/restaurant/menu')} data-testid="go-to-menu">
                  <UtensilsCrossed className="w-4 h-4 mr-2" />
                  Add Menu Items
                </Button>
                <Button variant="outline" onClick={() => navigate('/restaurant/surplus')}>
                  List Surplus Food
                </Button>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}
    </div>
  );
};

export default RegisterRestaurant;
