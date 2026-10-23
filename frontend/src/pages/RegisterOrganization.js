import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
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
  Building2, MapPin, Mail, Phone, Loader2, 
  CheckCircle, ArrowRight, Heart
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RegisterOrganization = () => {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [checkingExisting, setCheckingExisting] = useState(true);
  const [existingOrg, setExistingOrg] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    org_type: '',
    lat: '',
    lng: '',
    address: '',
    city: '',
    contact_email: user?.email || '',
    contact_phone: ''
  });

  useEffect(() => {
    checkExistingOrg();
  }, []);

  const checkExistingOrg = async () => {
    try {
      const res = await axios.get(`${API}/organizations?verified_only=false`, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      const myOrg = res.data.find(o => o.user_id === user?.user_id);
      if (myOrg) {
        setExistingOrg(myOrg);
      }
    } catch (error) {
      console.error('Check error:', error);
    } finally {
      setCheckingExisting(false);
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
    if (!formData.name || !formData.org_type || !formData.lat || !formData.lng) {
      toast.error('Name, type, and location are required');
      return;
    }

    setLoading(true);
    try {
      await axios.post(`${API}/organizations`, {
        name: formData.name,
        description: formData.description,
        org_type: formData.org_type,
        lat: parseFloat(formData.lat),
        lng: parseFloat(formData.lng),
        address: formData.address,
        city: formData.city,
        contact_email: formData.contact_email,
        contact_phone: formData.contact_phone
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });

      toast.success('Organization registered! Awaiting admin verification.');
      setStep(3);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  if (checkingExisting) {
    return (
      <div className="p-6 md:p-8 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  // If already has organization
  if (existingOrg) {
    return (
      <div className="p-6 md:p-8 max-w-2xl mx-auto">
        <Card className={existingOrg.is_verified ? 'border-green-500/50 bg-green-500/5' : 'border-amber-500/50 bg-amber-500/5'}>
          <CardContent className="p-8 text-center">
            {existingOrg.is_verified ? (
              <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
            ) : (
              <Building2 className="w-16 h-16 text-amber-500 mx-auto mb-4" />
            )}
            <h2 className="text-2xl font-bold mb-2">
              {existingOrg.is_verified ? 'Organization Verified!' : 'Verification Pending'}
            </h2>
            <p className="text-muted-foreground mb-2">
              <strong>{existingOrg.name}</strong>
            </p>
            <p className="text-muted-foreground mb-6">
              {existingOrg.is_verified 
                ? 'Your organization is verified. You can now reserve surplus food!'
                : 'Your organization is awaiting admin verification. You\'ll be able to reserve food once verified.'}
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <Button onClick={() => navigate('/organization/requests')}>
                <Heart className="w-4 h-4 mr-2" />
                Browse Available Food
              </Button>
              <Button variant="outline" onClick={() => navigate('/organization/received')}>
                View Received Food
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-2xl mx-auto" data-testid="register-organization-page">
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
                <Building2 className="w-6 h-6 text-primary" />
                Organization Details
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="name">Organization Name *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="Community Food Bank"
                  data-testid="org-name-input"
                />
              </div>

              <div className="space-y-2">
                <Label>Organization Type *</Label>
                <Select
                  value={formData.org_type}
                  onValueChange={(value) => setFormData(prev => ({ ...prev, org_type: value }))}
                >
                  <SelectTrigger data-testid="org-type-select">
                    <SelectValue placeholder="Select type..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="food_bank">Food Bank</SelectItem>
                    <SelectItem value="shelter">Homeless Shelter</SelectItem>
                    <SelectItem value="community_kitchen">Community Kitchen</SelectItem>
                    <SelectItem value="church">Church / Religious Org</SelectItem>
                    <SelectItem value="nonprofit">Other Nonprofit</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="Tell us about your organization and who you serve..."
                  rows={3}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="contact_email">Contact Email</Label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input
                      id="contact_email"
                      type="email"
                      value={formData.contact_email}
                      onChange={(e) => setFormData(prev => ({ ...prev, contact_email: e.target.value }))}
                      className="pl-10"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="contact_phone">Contact Phone</Label>
                  <div className="relative">
                    <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input
                      id="contact_phone"
                      type="tel"
                      value={formData.contact_phone}
                      onChange={(e) => setFormData(prev => ({ ...prev, contact_phone: e.target.value }))}
                      placeholder="(555) 123-4567"
                      className="pl-10"
                    />
                  </div>
                </div>
              </div>

              <Button 
                onClick={() => setStep(2)} 
                className="w-full"
                disabled={!formData.name || !formData.org_type}
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

              <div className="space-y-2">
                <Label htmlFor="city">City</Label>
                <Input
                  id="city"
                  value={formData.city}
                  onChange={(e) => setFormData(prev => ({ ...prev, city: e.target.value }))}
                  placeholder="New York"
                />
              </div>

              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <span className="text-green-500">🔒</span>
                Your location is encrypted using AES-256
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
                    <Building2 className="w-4 h-4 mr-2" />
                  )}
                  Register Organization
                </Button>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Step 3: Success / Pending */}
      {step === 3 && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <Card className="border-amber-500/50 bg-amber-500/5">
            <CardContent className="p-8 text-center">
              <Building2 className="w-16 h-16 text-amber-500 mx-auto mb-4" />
              <h2 className="text-2xl font-bold mb-2">Registration Submitted!</h2>
              <p className="text-muted-foreground mb-6">
                Your organization <strong>{formData.name}</strong> has been registered and is 
                awaiting admin verification. Once verified, you'll be able to reserve surplus food 
                from local restaurants.
              </p>
              <div className="p-4 rounded-xl bg-amber-100 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200 mb-6">
                <p className="text-sm">
                  <strong>What happens next?</strong><br />
                  An admin will review your organization and verify it. This helps ensure 
                  food goes to legitimate organizations serving the community.
                </p>
              </div>
              <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <Button onClick={() => navigate('/organization/requests')}>
                  Browse Available Food
                </Button>
                <Button variant="outline" onClick={() => navigate('/dashboard')}>
                  Go to Dashboard
                </Button>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}
    </div>
  );
};

export default RegisterOrganization;
