import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';
import { 
  Heart, Truck, Store, Users, TrendingUp, Leaf,
  UtensilsCrossed, DollarSign, MapPin
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CommunityImpact = () => {
  const { token } = useAuth();
  const [unavailable, setUnavailable] = useState(false);
  const [stats, setStats] = useState({
    meals_delivered: 0,
    meals_donated: 0,
    co2_saved: 0,
    money_saved: 0,
    active_restaurants: 0,
    active_drivers: 0,
    organizations_helped: 0,
    surplus_rescued: 0
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      // The impact feed is for every signed-in account; the numbers are
      // platform totals, not moderation data.
      const res = await axios.get(`${API}/impact/stats`, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setStats({
        meals_delivered: res.data.meals_delivered,
        meals_donated: res.data.meals_donated,
        co2_saved: Math.round(res.data.meals_donated * 2.5), // ~2.5kg CO2 per meal saved
        money_saved: Math.round(res.data.meals_donated * 8), // ~$8 per meal
        active_restaurants: res.data.active_restaurants,
        active_drivers: res.data.active_drivers,
        organizations_helped: res.data.organizations_helped,
        surplus_rescued: res.data.surplus_saved
      });
      setUnavailable(false);
    } catch (error) {
      // Zeros, not invented numbers: a demo figure here would read as a real
      // achievement on the page that is supposed to be evidence.
      setUnavailable(true);
    } finally {
      setLoading(false);
    }
  };

  const impactCards = [
    {
      title: 'Meals Delivered',
      value: stats.meals_delivered,
      icon: UtensilsCrossed,
      color: 'text-blue-600',
      bgColor: 'bg-blue-500/10',
      suffix: ''
    },
    {
      title: 'Meals Donated',
      value: stats.meals_donated,
      icon: Heart,
      color: 'text-pink-600',
      bgColor: 'bg-pink-500/10',
      suffix: ''
    },
    {
      title: 'CO₂ Saved',
      value: stats.co2_saved,
      icon: Leaf,
      color: 'text-green-600',
      bgColor: 'bg-green-500/10',
      suffix: ' kg'
    },
    {
      title: 'Food Value Saved',
      value: stats.money_saved,
      icon: DollarSign,
      color: 'text-amber-600',
      bgColor: 'bg-amber-500/10',
      prefix: '$'
    }
  ];

  const communityCards = [
    {
      title: 'Partner Restaurants',
      value: stats.active_restaurants,
      icon: Store,
      description: 'Local businesses fighting food waste'
    },
    {
      title: 'Active Drivers',
      value: stats.active_drivers,
      icon: Truck,
      description: 'Community members making deliveries'
    },
    {
      title: 'Organizations Helped',
      value: stats.organizations_helped,
      icon: Users,
      description: 'Shelters, food banks & community kitchens'
    },
    {
      title: 'Surplus Meals Rescued',
      value: stats.surplus_rescued,
      icon: TrendingUp,
      description: 'Meals saved from going to waste'
    }
  ];

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-32 bg-muted rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 space-y-8" data-testid="community-impact-page">
      {/* Header */}
      <div className="text-center max-w-2xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight">
            Our <span className="bg-clip-text text-transparent bg-gradient-to-r from-primary to-pink-500">Community Impact</span>
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Together, we're building a world where no food goes to waste and no one goes hungry.
          </p>
          {unavailable && (
            <p className="mt-2 text-sm text-destructive">
              Live impact figures are unavailable right now.
            </p>
          )}
        </motion.div>
      </div>

      {/* Main Impact Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {impactCards.map((card, i) => (
          <motion.div
            key={card.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <Card className={`${card.bgColor} border-0`}>
              <CardContent className="p-6 text-center">
                <card.icon className={`w-8 h-8 ${card.color} mx-auto mb-3`} />
                <p className={`text-3xl md:text-4xl font-bold font-mono ${card.color}`}>
                  {card.prefix || ''}{card.value.toLocaleString()}{card.suffix || ''}
                </p>
                <p className="text-sm text-muted-foreground mt-1">{card.title}</p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Visual Impact */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.3 }}
      >
        <Card className="overflow-hidden">
          <div className="p-8 bg-gradient-to-br from-primary/10 via-pink-500/10 to-amber-500/10">
            <div className="text-center space-y-4">
              <p className="text-xl text-muted-foreground">That's equivalent to</p>
              <div className="flex flex-wrap justify-center gap-8 md:gap-16">
                <div>
                  <p className="text-5xl md:text-6xl font-bold text-green-600">
                    {Math.round(stats.co2_saved / 4000)}
                  </p>
                  <p className="text-muted-foreground">Trees planted</p>
                </div>
                <div>
                  <p className="text-5xl md:text-6xl font-bold text-blue-600">
                    {Math.round(stats.meals_donated / 3)}
                  </p>
                  <p className="text-muted-foreground">Families fed</p>
                </div>
                <div>
                  <p className="text-5xl md:text-6xl font-bold text-pink-600">
                    {Math.round(stats.co2_saved / 8.9)}
                  </p>
                  <p className="text-muted-foreground">Car trips saved</p>
                </div>
              </div>
            </div>
          </div>
        </Card>
      </motion.div>

      {/* Community Stats */}
      <div>
        <h2 className="text-2xl font-bold mb-6">Our Community</h2>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
          {communityCards.map((card, i) => (
            <motion.div
              key={card.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 + i * 0.1 }}
            >
              <Card className="h-full">
                <CardContent className="p-6">
                  <div className="flex items-center gap-4 mb-4">
                    <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
                      <card.icon className="w-6 h-6 text-primary" />
                    </div>
                    <p className="text-3xl font-bold font-mono">{card.value}</p>
                  </div>
                  <h3 className="font-semibold">{card.title}</h3>
                  <p className="text-sm text-muted-foreground mt-1">{card.description}</p>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Call to Action */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6 }}
      >
        <Card className="bg-primary/5 border-primary/20">
          <CardContent className="p-8 text-center">
            <Heart className="w-12 h-12 text-pink-500 mx-auto mb-4" />
            <h3 className="text-2xl font-bold mb-2">Every Order Makes a Difference</h3>
            <p className="text-muted-foreground max-w-2xl mx-auto">
              When you order through SharePlate, you're not just getting food—you're supporting 
              local restaurants, fair driver pay, and food distribution to those in need. 
              Thank you for being part of our community.
            </p>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};

export default CommunityImpact;
