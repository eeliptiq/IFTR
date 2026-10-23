import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import axios from 'axios';
import { toast } from 'sonner';
import { imageSrc } from '../lib/images';
import { 
  Store, Search, MapPin, Star, Clock, Filter, 
  ChevronRight, UtensilsCrossed
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const Restaurants = () => {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [restaurants, setRestaurants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [cuisine, setCuisine] = useState('');

  useEffect(() => {
    fetchRestaurants();
  }, [cuisine]);

  const fetchRestaurants = async () => {
    try {
      const params = new URLSearchParams();
      if (cuisine) params.append('cuisine', cuisine);
      
      const res = await axios.get(`${API}/restaurants?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        withCredentials: true
      });
      setRestaurants(res.data);
    } catch (error) {
      toast.error('Failed to load restaurants');
    } finally {
      setLoading(false);
    }
  };

  const filteredRestaurants = restaurants.filter(r => 
    r.name.toLowerCase().includes(search.toLowerCase()) ||
    r.cuisine_type?.toLowerCase().includes(search.toLowerCase())
  );

  const cuisines = ['All', 'Italian', 'Mexican', 'Chinese', 'Indian', 'American', 'Japanese'];

  return (
    <div className="p-6 md:p-8 space-y-8" data-testid="restaurants-page">
      {/* Header */}
      <div className="space-y-4">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
          Find Restaurants
        </h1>
        
        {/* Search */}
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
            <Input
              placeholder="Search restaurants or cuisine..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 h-12"
              data-testid="restaurant-search"
            />
          </div>
        </div>

        {/* Cuisine Filter */}
        <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
          {cuisines.map((c) => (
            <Button
              key={c}
              variant={cuisine === (c === 'All' ? '' : c.toLowerCase()) ? 'default' : 'outline'}
              size="sm"
              className="rounded-full whitespace-nowrap"
              onClick={() => setCuisine(c === 'All' ? '' : c.toLowerCase())}
              data-testid={`cuisine-${c.toLowerCase()}`}
            >
              {c}
            </Button>
          ))}
        </div>
      </div>

      {/* Restaurant Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[...Array(6)].map((_, i) => (
            <Card key={i} className="animate-pulse">
              <div className="h-48 bg-muted" />
              <CardContent className="p-4">
                <div className="h-6 bg-muted rounded w-3/4 mb-2" />
                <div className="h-4 bg-muted rounded w-1/2" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : filteredRestaurants.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Store className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">No restaurants found</p>
            <p className="text-sm text-muted-foreground mt-1">Try adjusting your search or filters</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredRestaurants.map((restaurant, i) => (
            <motion.div
              key={restaurant.restaurant_id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
            >
              <Card 
                className="overflow-hidden cursor-pointer hover:shadow-lg transition-shadow group"
                onClick={() => navigate(`/restaurants/${restaurant.restaurant_id}`)}
                data-testid={`restaurant-card-${restaurant.restaurant_id}`}
              >
                {/* Image */}
                <div className="relative h-48 bg-secondary overflow-hidden">
                  {restaurant.image_url ? (
                    <img
                      src={imageSrc(restaurant.image_url)}
                      alt={restaurant.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <UtensilsCrossed className="w-12 h-12 text-muted-foreground" />
                    </div>
                  )}
                  {restaurant.cuisine_type && (
                    <Badge className="absolute top-3 left-3">
                      {restaurant.cuisine_type}
                    </Badge>
                  )}
                </div>

                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="font-bold text-lg">{restaurant.name}</h3>
                      <p className="text-sm text-muted-foreground line-clamp-1 mt-1">
                        {restaurant.description || 'Delicious food awaits'}
                      </p>
                    </div>
                    {restaurant.rating > 0 && (
                      <div className="flex items-center gap-1 bg-primary/10 px-2 py-1 rounded-full">
                        <Star className="w-4 h-4 text-primary fill-primary" />
                        <span className="text-sm font-semibold">{restaurant.rating.toFixed(1)}</span>
                      </div>
                    )}
                  </div>
                  
                  <div className="flex items-center gap-4 mt-4 text-sm text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <Clock className="w-4 h-4" />
                      <span>25-35 min</span>
                    </div>
                    {restaurant.distance_km && (
                      <div className="flex items-center gap-1">
                        <MapPin className="w-4 h-4" />
                        <span>{restaurant.distance_km.toFixed(1)} km</span>
                      </div>
                    )}
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

export default Restaurants;
