# CreditMate AI - Frontend Implementation Guide

This document provides complete instructions for implementing the Next.js frontend that connects to the Django backend.

## Quick Start

```bash
# Create Next.js app in frontend directory
cd /home/user/creditmate-ai-be
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --import-alias "@/*"

# Install additional dependencies
cd frontend
npm install axios react-query @tanstack/react-query zustand lucide-react class-variance-authority clsx tailwind-merge
npm install -D @types/node

# Start development server
npm run dev
```

## Project Structure

```
frontend/
├── src/
│   ├── app/                      # Next.js 14 App Router
│   │   ├── layout.tsx           # Root layout
│   │   ├── page.tsx             # Homepage
│   │   ├── cards/               # Credit card pages
│   │   │   ├── page.tsx         # List all cards
│   │   │   └── [id]/page.tsx   # Card details with reviews
│   │   ├── categories/          # Benefit category pages
│   │   │   ├── page.tsx         # List categories
│   │   │   └── [id]/page.tsx   # Category details
│   │   ├── compare/             # Comparison tool
│   │   │   └── page.tsx
│   │   └── search/              # Search page
│   │       └── page.tsx
│   ├── components/               # Reusable components
│   │   ├── cards/               # Card-related components
│   │   │   ├── CardList.tsx
│   │   │   ├── CardDetail.tsx
│   │   │   ├── CardCompare.tsx
│   │   │   └── CardFilters.tsx
│   │   ├── reviews/             # Review components
│   │   │   ├── ReviewList.tsx
│   │   │   ├── ReviewForm.tsx
│   │   │   └── RatingStars.tsx
│   │   ├── layout/              # Layout components
│   │   │   ├── Header.tsx
│   │   │   ├── Footer.tsx
│   │   │   └── Sidebar.tsx
│   │   └── ui/                  # UI primitives
│   │       ├── Button.tsx
│   │       ├── Card.tsx
│   │       ├── Input.tsx
│   │       └── Badge.tsx
│   ├── lib/                      # Utilities
│   │   ├── api/                 # API client
│   │   │   ├── client.ts
│   │   │   ├── cards.ts
│   │   │   ├── reviews.ts
│   │   │   └── categories.ts
│   │   ├── hooks/               # Custom hooks
│   │   │   ├── useCards.ts
│   │   │   ├── useReviews.ts
│   │   │   └── useComparison.ts
│   │   └── utils.ts             # Helper functions
│   └── types/                    # TypeScript types
│       └── index.ts
├── public/                       # Static assets
├── next.config.js
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

## API Client Implementation

### `src/lib/api/client.ts`

```typescript
import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized
      localStorage.removeItem('token');
    }
    return Promise.reject(error);
  }
);
```

### `src/lib/api/cards.ts`

```typescript
import { apiClient } from './client';
import { CreditCard, CreditCardFilters } from '@/types';

export const cardsApi = {
  // Get all cards with filters
  getCards: async (filters?: CreditCardFilters) => {
    const { data } = await apiClient.get('/credit-cards', { params: filters });
    return data;
  },

  // Get single card
  getCard: async (id: number) => {
    const { data } = await apiClient.get(`/credit-cards/${id}`);
    return data;
  },

  // Get cards by benefit category
  getCardsByCategory: async (categoryId: number) => {
    const { data } = await apiClient.get(`/benefit-categories/${categoryId}/cards`);
    return data;
  },

  // Get benefit categories
  getCategories: async () => {
    const { data } = await apiClient.get('/benefit-categories');
    return data;
  },

  // Search suggestions
  getSearchSuggestions: async () => {
    const { data} = await apiClient.get('/credit-cards/search_suggestions');
    return data;
  },
};
```

### `src/lib/api/reviews.ts`

```typescript
import { apiClient } from './client';

export const reviewsApi = {
  // Get reviews for a card
  getReviews: async (cardId: number) => {
    const { data } = await apiClient.get('/reviews', { params: { credit_card: cardId } });
    return data;
  },

  // Submit a review
  submitReview: async (reviewData: any) => {
    const { data } = await apiClient.post('/reviews', reviewData);
    return data;
  },

  // Mark review as helpful
  markHelpful: async (reviewId: number) => {
    const { data } = await apiClient.post(`/reviews/${reviewId}/mark_helpful`);
    return data;
  },

  // Get ratings for a card
  getRatings: async (cardId: number) => {
    const { data } = await apiClient.get('/ratings', { params: { credit_card: cardId } });
    return data;
  },

  // Submit a rating
  submitRating: async (ratingData: any) => {
    const { data } = await apiClient.post('/ratings', ratingData);
    return data;
  },
};
```

## TypeScript Types

### `src/types/index.ts`

```typescript
export interface Bank {
  id: number;
  name: string;
  logo: string;
  website: string;
}

export interface BenefitCategory {
  id: number;
  name: string;
  category_type: string;
  description: string;
  icon: string;
  display_order: number;
}

export interface CreditCardBenefit {
  id: number;
  benefit_category: BenefitCategory;
  reward_rate: number | null;
  reward_description: string;
  conditions: string;
  is_primary: boolean;
  confidence_score: number;
}

export interface CreditCard {
  id: number;
  bank: Bank;
  name: string;
  annual_fee: number;
  interest_rate_apr: number;
  apply_url: string;
  annual_fee_waiver_difficulty: string;
  spending_tier: string;
  best_for_tags: string[];
  lounge_access_international: string;
  lounge_access_domestic: string;
  has_lounge_access: boolean;
  has_annual_fee: boolean;
  average_rating: number | null;
  total_ratings: number;
  total_reviews: number;
  card_benefits: CreditCardBenefit[];
  is_active: boolean;
  created: string;
  modified: string;
}

export interface Review {
  id: number;
  user_name: string;
  title: string;
  review_text: string;
  rating: number;
  pros: string;
  cons: string;
  helpful_count: number;
  usage_duration_months: number | null;
  is_verified_user: boolean;
  created: string;
}

export interface CreditCardFilters {
  bank?: number;
  annual_fee_min?: number;
  annual_fee_max?: number;
  waiver_difficulty?: string;
  tier?: string;
  benefit_category?: number;
  search?: string;
  ordering?: string;
}
```

## Key Components

### Card List Component
Displays grid of credit cards with filtering and sorting

### Card Detail Component
Shows full card information, benefits, and reviews

### Review Form Component
Allows users to submit reviews and ratings

### Comparison Tool Component
Side-by-side comparison of up to 4 cards

### Rating Stars Component
Interactive star rating display and input

## Environment Variables

Create `.env.local` in frontend directory:

```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_APP_NAME=CreditMate AI
```

## Docker Integration

The frontend will be built as part of the Docker Compose setup.
