import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Textarea } from '../components/ui/textarea';
import { Input } from '../components/ui/input';
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
  MapPin, Clock, AlertTriangle, Lightbulb, ThumbsUp, 
  Plus, Navigation, Car, Bike, Search, Filter
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Using the support Q&A system for route tips
const DriverRouting = () => {
  const { token, user } = useAuth();
  const [tips, setTips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [searchArea, setSearchArea] = useState('');
  const [newTip, setNewTip] = useState({
    area: '',
    tip_type: 'shortcut',
    description: '',
    time_relevant: ''
  });

  useEffect(() => {
    fetchTips();
  }, [filter]);

  const fetchTips = async () => {
    try {
      // Use support questions with category "routing" for route tips
      const res = await axios.get(`${API}/support/questions?category=routing`, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      setTips(res.data);
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handlePostTip = async () => {
    if (!newTip.area || !newTip.description) {
      toast.error('Area and description are required');
      return;
    }

    try {
      const tipText = `[${newTip.tip_type.toUpperCase()}] ${newTip.area}\n\n${newTip.description}${
        newTip.time_relevant ? `\n\n⏰ Best time: ${newTip.time_relevant}` : ''
      }`;

      await axios.post(`${API}/support/questions`, {
        question: tipText,
        category: 'routing'
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      
      toast.success('Route tip shared with the community!');
      setDialogOpen(false);
      setNewTip({ area: '', tip_type: 'shortcut', description: '', time_relevant: '' });
      fetchTips();
    } catch (error) {
      toast.error('Failed to post tip');
    }
  };

  const handleUpvote = async (answerId) => {
    try {
      await axios.post(`${API}/support/answers/${answerId}/upvote`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      fetchTips();
    } catch (error) {
      toast.error('Failed to upvote');
    }
  };

  const handleConfirm = async (questionId, answer) => {
    try {
      await axios.post(`${API}/support/answers`, {
        question_id: questionId,
        answer
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success('Confirmation added!');
      fetchTips();
    } catch (error) {
      toast.error('Failed to add confirmation');
    }
  };

  const getTipTypeIcon = (text) => {
    if (text.includes('[SHORTCUT]')) return <Navigation className="w-4 h-4 text-green-600" />;
    if (text.includes('[PARKING]')) return <Car className="w-4 h-4 text-blue-600" />;
    if (text.includes('[HAZARD]')) return <AlertTriangle className="w-4 h-4 text-red-600" />;
    if (text.includes('[TIMING]')) return <Clock className="w-4 h-4 text-amber-600" />;
    return <Lightbulb className="w-4 h-4 text-purple-600" />;
  };

  const getTipTypeBadge = (text) => {
    if (text.includes('[SHORTCUT]')) return <Badge className="bg-green-100 text-green-700">Shortcut</Badge>;
    if (text.includes('[PARKING]')) return <Badge className="bg-blue-100 text-blue-700">Parking</Badge>;
    if (text.includes('[HAZARD]')) return <Badge className="bg-red-100 text-red-700">Hazard</Badge>;
    if (text.includes('[TIMING]')) return <Badge className="bg-amber-100 text-amber-700">Timing</Badge>;
    return <Badge className="bg-purple-100 text-purple-700">Tip</Badge>;
  };

  const parseTip = (text) => {
    const lines = text.split('\n');
    const firstLine = lines[0] || '';
    const area = firstLine.replace(/\[(SHORTCUT|PARKING|HAZARD|TIMING|TIP)\]\s*/i, '');
    const description = lines.slice(2).join('\n').replace(/⏰ Best time:.*$/m, '').trim();
    const timeMatch = text.match(/⏰ Best time: (.+)/);
    return { area, description, time: timeMatch?.[1] };
  };

  const filteredTips = tips.filter(tip => {
    if (!searchArea) return true;
    return tip.question.toLowerCase().includes(searchArea.toLowerCase());
  });

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="driver-routing-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <MapPin className="w-8 h-8 text-primary" />
            Route Tips
          </h1>
          <p className="text-muted-foreground">
            Community-shared knowledge about local routes and delivery areas
          </p>
        </div>
        
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button data-testid="share-tip-button">
              <Plus className="w-4 h-4 mr-2" />
              Share a Tip
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Share Route Knowledge</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Area / Location</label>
                <Input
                  value={newTip.area}
                  onChange={(e) => setNewTip(prev => ({ ...prev, area: e.target.value }))}
                  placeholder="e.g., Oak Street & Main, Downtown district"
                  data-testid="tip-area-input"
                />
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">Type of Tip</label>
                <Select
                  value={newTip.tip_type}
                  onValueChange={(value) => setNewTip(prev => ({ ...prev, tip_type: value }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="shortcut">
                      <div className="flex items-center gap-2">
                        <Navigation className="w-4 h-4 text-green-600" />
                        Shortcut
                      </div>
                    </SelectItem>
                    <SelectItem value="parking">
                      <div className="flex items-center gap-2">
                        <Car className="w-4 h-4 text-blue-600" />
                        Parking Spot
                      </div>
                    </SelectItem>
                    <SelectItem value="hazard">
                      <div className="flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4 text-red-600" />
                        Hazard / Avoid
                      </div>
                    </SelectItem>
                    <SelectItem value="timing">
                      <div className="flex items-center gap-2">
                        <Clock className="w-4 h-4 text-amber-600" />
                        Timing Tip
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Textarea
                  value={newTip.description}
                  onChange={(e) => setNewTip(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="Share what you know... e.g., 'The back entrance on 2nd Ave is faster after 5pm'"
                  rows={3}
                  data-testid="tip-description-input"
                />
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">Time Relevant (optional)</label>
                <Input
                  value={newTip.time_relevant}
                  onChange={(e) => setNewTip(prev => ({ ...prev, time_relevant: e.target.value }))}
                  placeholder="e.g., After 5pm, Weekday mornings, Tuesdays"
                />
              </div>
              
              <Button onClick={handlePostTip} className="w-full" data-testid="submit-tip-button">
                Share with Community
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
        <Input
          value={searchArea}
          onChange={(e) => setSearchArea(e.target.value)}
          placeholder="Search by area..."
          className="pl-10"
          data-testid="search-tips"
        />
      </div>

      {/* Tips List */}
      {loading ? (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-32 bg-muted rounded-xl animate-pulse" />
          ))}
        </div>
      ) : filteredTips.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <MapPin className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">No route tips yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Be the first to share local knowledge!
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {filteredTips.map((tip, i) => {
            const parsed = parseTip(tip.question);
            const confirmations = tip.answers?.length || 0;
            
            return (
              <motion.div
                key={tip.question_id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <Card data-testid={`tip-${tip.question_id}`}>
                  <CardContent className="p-6">
                    <div className="flex items-start gap-4">
                      <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
                        {getTipTypeIcon(tip.question)}
                      </div>
                      
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-2">
                          {getTipTypeBadge(tip.question)}
                          <span className="font-semibold">{parsed.area}</span>
                        </div>
                        
                        <p className="text-muted-foreground">{parsed.description}</p>
                        
                        {parsed.time && (
                          <p className="text-sm text-amber-600 mt-2 flex items-center gap-1">
                            <Clock className="w-4 h-4" />
                            {parsed.time}
                          </p>
                        )}
                        
                        <div className="flex items-center gap-4 mt-4">
                          <span className="text-sm text-muted-foreground">
                            Shared by {tip.user_name || 'Driver'}
                          </span>
                          
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleConfirm(tip.question_id, 'I can confirm this tip works!')}
                            className="gap-1"
                          >
                            <ThumbsUp className="w-4 h-4" />
                            Confirm ({confirmations})
                          </Button>
                        </div>
                        
                        {/* Confirmations */}
                        {tip.answers?.length > 0 && (
                          <div className="mt-4 pl-4 border-l-2 border-green-500/30 space-y-2">
                            {tip.answers.slice(0, 3).map((a) => (
                              <p key={a.answer_id} className="text-sm text-muted-foreground">
                                ✓ {a.user_name || 'Driver'}: {a.answer}
                              </p>
                            ))}
                            {tip.answers.length > 3 && (
                              <p className="text-xs text-muted-foreground">
                                +{tip.answers.length - 3} more confirmations
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default DriverRouting;
