import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
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
  DialogTrigger,
} from '../components/ui/dialog';
import axios from 'axios';
import { toast } from 'sonner';
import { 
  HelpCircle, MessageSquare, ThumbsUp, CheckCircle,
  Plus, Send, User, Truck, Store
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const Support = () => {
  const { user, token } = useAuth();
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [newQuestion, setNewQuestion] = useState({ question: '', category: 'general' });
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    fetchQuestions();
  }, [filter]);

  const fetchQuestions = async () => {
    try {
      const params = new URLSearchParams();
      if (filter) params.append('category', filter);
      
      const res = await axios.get(`${API}/support/questions?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        withCredentials: true
      });
      setQuestions(res.data);
    } catch (error) {
      toast.error('Failed to load questions');
    } finally {
      setLoading(false);
    }
  };

  const handleAskQuestion = async () => {
    if (!newQuestion.question.trim()) {
      toast.error('Please enter a question');
      return;
    }

    try {
      await axios.post(`${API}/support/questions`, newQuestion, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success('Question posted!');
      setNewQuestion({ question: '', category: 'general' });
      setDialogOpen(false);
      fetchQuestions();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to post question');
    }
  };

  const handleAnswer = async (questionId, answer) => {
    try {
      await axios.post(`${API}/support/answers`, {
        question_id: questionId,
        answer
      }, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success('Answer posted!');
      fetchQuestions();
    } catch (error) {
      toast.error('Failed to post answer');
    }
  };

  const handleUpvote = async (answerId) => {
    try {
      await axios.post(`${API}/support/answers/${answerId}/upvote`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      fetchQuestions();
    } catch (error) {
      toast.error('Failed to upvote');
    }
  };

  const handleAccept = async (answerId) => {
    try {
      await axios.post(`${API}/support/answers/${answerId}/accept`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true
      });
      toast.success('Marked as the answer');
      fetchQuestions();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to accept answer');
    }
  };

  const getRoleIcon = (role) => {
    switch (role) {
      case 'driver':
        return <Truck className="w-4 h-4" />;
      case 'restaurant':
        return <Store className="w-4 h-4" />;
      default:
        return <User className="w-4 h-4" />;
    }
  };

  const categories = [
    { value: '', label: 'All Categories' },
    { value: 'general', label: 'General' },
    { value: 'delivery', label: 'Delivery' },
    { value: 'payment', label: 'Payment' },
    { value: 'restaurant', label: 'Restaurant' },
    { value: 'technical', label: 'Technical' }
  ];

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="support-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Community Support</h1>
          <p className="text-muted-foreground mt-1">
            Get help from drivers and customers who understand common issues
          </p>
        </div>
        
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button className="btn-pill" data-testid="ask-question-button">
              <Plus className="w-4 h-4 mr-2" />
              Ask Question
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Ask a Question</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div className="space-y-2">
                <Select
                  value={newQuestion.category}
                  onValueChange={(value) => setNewQuestion(prev => ({ ...prev, category: value }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select category" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="general">General</SelectItem>
                    <SelectItem value="delivery">Delivery</SelectItem>
                    <SelectItem value="payment">Payment</SelectItem>
                    <SelectItem value="restaurant">Restaurant</SelectItem>
                    <SelectItem value="technical">Technical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Textarea
                placeholder="What would you like to know?"
                value={newQuestion.question}
                onChange={(e) => setNewQuestion(prev => ({ ...prev, question: e.target.value }))}
                rows={4}
                data-testid="question-input"
              />
              <Button onClick={handleAskQuestion} className="w-full" data-testid="submit-question-button">
                <Send className="w-4 h-4 mr-2" />
                Post Question
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Filter */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
        {categories.map((cat) => (
          <Button
            key={cat.value}
            variant={filter === cat.value ? 'default' : 'outline'}
            size="sm"
            className="rounded-full whitespace-nowrap"
            onClick={() => setFilter(cat.value)}
          >
            {cat.label}
          </Button>
        ))}
      </div>

      {/* Questions List */}
      {loading ? (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <Card key={i} className="animate-pulse">
              <CardContent className="p-6">
                <div className="h-24 bg-muted rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : questions.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <HelpCircle className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">No questions yet</p>
            <p className="text-sm text-muted-foreground mt-1">Be the first to ask!</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {questions.map((q, i) => (
            <QuestionCard
              key={q.question_id}
              question={q}
              index={i}
              user={user}
              token={token}
              onAnswer={handleAnswer}
              onUpvote={handleUpvote}
              onAccept={handleAccept}
              getRoleIcon={getRoleIcon}
            />
          ))}
        </div>
      )}
    </div>
  );
};

const QuestionCard = ({ question, index, user, token, onAnswer, onUpvote, onAccept, getRoleIcon }) => {
  const [showAnswerForm, setShowAnswerForm] = useState(false);
  const [answer, setAnswer] = useState('');

  const handleSubmitAnswer = () => {
    if (!answer.trim()) return;
    onAnswer(question.question_id, answer);
    setAnswer('');
    setShowAnswerForm(false);
  };

  const getCategoryColor = (category) => {
    const colors = {
      general: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
      delivery: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400',
      payment: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
      restaurant: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
      technical: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
    };
    return colors[category] || colors.general;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
    >
      <Card className="question-card" data-testid={`question-${question.question_id}`}>
        <CardContent className="p-6">
          {/* Question Header */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                {getRoleIcon(question.user_role)}
              </div>
              <div>
                <p className="font-semibold">{question.user_name || 'Anonymous'}</p>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="capitalize">{question.user_role}</span>
                  <span>•</span>
                  <span>{new Date(question.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge className={getCategoryColor(question.category)}>
                {question.category}
              </Badge>
              {question.is_resolved && (
                <Badge variant="secondary" className="bg-green-100 text-green-700">
                  <CheckCircle className="w-3 h-3 mr-1" />
                  Resolved
                </Badge>
              )}
            </div>
          </div>

          {/* Question Content */}
          <p className="mt-4 text-lg">{question.question}</p>

          {/* Answers */}
          {question.answers?.length > 0 && (
            <div className="mt-6 space-y-4">
              <p className="text-sm font-semibold text-muted-foreground">
                {question.answers.length} Answer{question.answers.length !== 1 ? 's' : ''}
              </p>
              {question.answers.map((a) => (
                <div
                  key={a.answer_id}
                  className={`answer-card ${a.is_accepted ? 'accepted' : ''}`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center">
                        {getRoleIcon(a.user_role)}
                      </div>
                      <div>
                        <p className="font-medium text-sm">{a.user_name || 'Anonymous'}</p>
                        <p className="text-xs text-muted-foreground capitalize">{a.user_role}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {/* Only the asker can accept, and only one answer stays
                          accepted; the backend moves the mark. */}
                      {question.is_mine && !a.is_accepted && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onAccept(a.answer_id)}
                          className="gap-1"
                          data-testid={`support-accept-${a.answer_id}`}
                        >
                          <CheckCircle className="w-4 h-4" />
                          Accept
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onUpvote(a.answer_id)}
                        className="gap-1"
                        data-testid={`support-upvote-${a.answer_id}`}
                      >
                        <ThumbsUp className="w-4 h-4" />
                        {a.upvotes}
                      </Button>
                    </div>
                  </div>
                  <p className="mt-2 text-sm">{a.answer}</p>
                  {a.is_accepted && (
                    <Badge variant="secondary" className="mt-2 bg-green-100 text-green-700">
                      <CheckCircle className="w-3 h-3 mr-1" />
                      Accepted Answer
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Answer Form */}
          {user && (
            <div className="mt-6">
              {showAnswerForm ? (
                <div className="space-y-3">
                  <Textarea
                    placeholder="Share your knowledge..."
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    rows={3}
                  />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={handleSubmitAnswer}>
                      Post Answer
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setShowAnswerForm(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowAnswerForm(true)}
                >
                  <MessageSquare className="w-4 h-4 mr-2" />
                  Answer this question
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default Support;
