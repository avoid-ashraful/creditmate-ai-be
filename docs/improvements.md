# Credit Card Data Extraction Improvements Plan

## 🎯 Executive Summary

This document outlines a comprehensive plan to fix data consistency issues in the credit card crawler system, specifically addressing missing `annual_fee` and `interest_rate_apr` data. The plan is structured in phases with clear priorities and implementation timelines.

## 🚨 Root Cause Analysis

### Critical Issues Identified:

1. **Silent Data Loss Through Default Values**
   - **Location**: `credit_card_data_service.py:135-138`, `credit_card_validator.py:353-362`
   - **Problem**: Missing or invalid `annual_fee` and `interest_rate_apr` are silently converted to `0`
   - **Impact**: Cannot distinguish between genuinely free cards and failed extractions

2. **LLM Parsing Inconsistencies**
   - Multiple AI models (OpenRouter → Gemini fallback) create inconsistent parsing
   - Temperature setting of 0.1 still allows variation in responses
   - Single complex prompt trying to handle all bank document formats

3. **Content Extraction Reliability Issues**
   - OCR dependency for image-based PDFs is error-prone
   - Different extraction methods have varying reliability
   - No quality scoring for extracted content

## 💡 Comprehensive Solution Strategy

### Phase 1: Immediate Fixes (Week 1-2) - HIGH PRIORITY

#### 1.1 Fix Silent Data Loss Issue

**Database Schema Updates:**
```python
# Update credit_cards/models.py
class CreditCard(Audit):
    # Change from required fields with default 0 to nullable fields
    annual_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,  # Allow NULL for missing data
        validators=[MinValueValidator(0)]
    )
    interest_rate_apr = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,  # Allow NULL for missing data
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
```

**Migration Required:**
```bash
python manage.py makemigrations
python manage.py migrate
```

**Validator Updates:**
```python
# Update banks/validators/credit_card_validator.py
@staticmethod
def _sanitize_numeric_fields(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve NULL for missing data instead of defaulting to 0"""
    sanitized = {}
    numeric_fields = ["annual_fee", "interest_rate_apr"]

    for field in numeric_fields:
        value = card_data.get(field)
        if value is not None and value != "" and value != "N/A":
            try:
                sanitized[field] = max(0, float(value))
            except (ValueError, TypeError):
                sanitized[field] = None  # Keep as NULL for failed parsing
        else:
            sanitized[field] = None  # NULL for missing data

    return sanitized
```

#### 1.2 Add Data Quality Tracking

**Enhanced CrawledContent Model:**
```python
# Update banks/models.py
class CrawledContent(Audit):
    # ... existing fields ...

    # New fields for quality tracking
    extraction_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Confidence score (0-1) for extraction quality"
    )
    missing_critical_fields = models.JSONField(
        default=list,
        help_text="List of critical fields that failed to extract"
    )
    extraction_method = models.CharField(
        max_length=50,
        blank=True,
        help_text="Method used: 'pdf_text', 'ocr', 'webpage', 'csv'"
    )
    needs_manual_review = models.BooleanField(
        default=False,
        help_text="Flag for content requiring manual review"
    )
```

**Quality Validation Service:**
```python
# Create banks/services/quality_validator.py
class ExtractionQualityValidator:

    @staticmethod
    def validate_extraction_quality(crawled_content):
        """Post-extraction quality validation"""
        issues = []
        confidence = 1.0

        parsed_data = crawled_content.parsed_json
        if not parsed_data:
            return 0.0, ["no_parsed_data"]

        # Check for critical missing fields
        if not parsed_data.get("annual_fee"):
            issues.append("missing_annual_fee")
            confidence *= 0.5

        if not parsed_data.get("interest_rate_apr"):
            issues.append("missing_interest_rate")
            confidence *= 0.5

        # Check content length (OCR failures are usually short)
        if len(crawled_content.extracted_content) < 100:
            issues.append("insufficient_content")
            confidence *= 0.3

        # Penalize OCR-based extractions
        if crawled_content.extraction_method == "ocr":
            confidence *= 0.7

        return min(confidence, 1.0), issues
```

### Phase 2: Enhanced LLM Parsing Strategy (Week 3-4)

#### 2.1 Multi-Pass Extraction Approach

**Enhanced LLM Parser:**
```python
# Update banks/services/llm_parser.py
class EnhancedLLMContentParser(LLMContentParser):

    def parse_with_multi_pass(self, content: str, bank_name: str):
        """Multi-pass extraction with validation"""

        # Pass 1: Standard extraction
        try:
            standard_result = self.parse_credit_card_data(content, bank_name)
            confidence_1 = self._calculate_completeness(standard_result)
        except Exception as e:
            logger.warning(f"Standard extraction failed: {e}")
            standard_result = []
            confidence_1 = 0.0

        # Pass 2: If critical fields missing, focused extraction
        if confidence_1 < 0.8:
            focused_result = self._extract_critical_fields_focused(content, bank_name)
            # Merge results
            final_result = self._merge_extraction_results(standard_result, focused_result)
        else:
            final_result = standard_result

        # Pass 3: Validation and confidence scoring
        final_confidence = self._calculate_final_confidence(final_result, content)

        return final_result, final_confidence

    def _extract_critical_fields_focused(self, content: str, bank_name: str):
        """Dedicated extraction for annual_fee and interest_rate_apr only"""
        prompt = f"""
        Extract ONLY annual fee and interest rate from this {bank_name} document.

        CRITICAL INSTRUCTIONS:
        1. Look for these exact patterns:
           - Annual Fee: "TK 5,000", "US$ 50", "Free", "No annual fee"
           - Interest Rate: "20% p.a.", "2.5% monthly", "24% per annum"

        2. Return JSON: {{"cards": [{{"annual_fee": number_or_null, "interest_rate_apr": number_or_null}}]}}

        3. IMPORTANT: Use null for truly missing data, don't guess or default to 0

        4. Convert formats properly:
           - "Free" → 0
           - "TK 5,000" → 5000
           - "20% p.a." → 20.0

        Content to analyze:
        {content[:3000]}  # Limit content to avoid token limits
        """

        return self._generate_ai_response(prompt, bank_name)
```

#### 2.2 Bank-Specific Prompt Engineering

**Bank-Specific Prompt Templates:**
```python
# Create banks/services/prompt_templates.py
class BankSpecificPrompts:

    DUTCH_BANGLA_TEMPLATE = """
    This is a Dutch-Bangla Bank document. Focus on table structures.
    Look for:
    - Card types: Visa Classic, Visa Gold, Visa Platinum
    - Annual Fee column (usually in TK)
    - Interest Rate column (usually as % p.a.)

    {base_instructions}
    """

    SONALI_BANK_TEMPLATE = """
    This is a Sonali Bank schedule of charges document.
    Look for:
    - Credit Card sections
    - Fee schedules in tabular format
    - Interest rates may be listed separately

    {base_instructions}
    """

    @classmethod
    def get_prompt_for_bank(cls, bank_name: str, content: str) -> str:
        """Get bank-specific prompt template"""

        bank_templates = {
            "Dutch-Bangla Bank Limited": cls.DUTCH_BANGLA_TEMPLATE,
            "BRAC Bank Limited": cls.DUTCH_BANGLA_TEMPLATE,  # Similar table format
            "Sonali Bank Limited": cls.SONALI_BANK_TEMPLATE,
            "Janata Bank Limited": cls.SONALI_BANK_TEMPLATE,  # Similar format
        }

        template = bank_templates.get(bank_name, cls._get_generic_template())
        base_instructions = cls._get_base_extraction_instructions()

        return template.format(
            base_instructions=base_instructions,
            bank_name=bank_name,
            content=content
        )
```

### Phase 3: Content Extraction Improvements (Week 5-6)

#### 3.1 Multi-Source Validation

**Enhanced Content Extractor:**
```python
# Update banks/services/content_extractor.py
class EnhancedContentExtractor(ContentExtractor):

    def extract_with_validation(self, url: str, content_type: str):
        """Extract content with multiple validation methods"""

        raw_content = self._fetch_content(url)
        extraction_results = []

        # Primary extraction
        try:
            primary_content = self._process_content(raw_content, content_type, url)
            primary_confidence = self._calculate_extraction_confidence(
                primary_content, content_type
            )
            extraction_results.append({
                'content': primary_content,
                'confidence': primary_confidence,
                'method': content_type
            })
        except Exception as e:
            logger.warning(f"Primary extraction failed: {e}")

        # For PDFs, try both text extraction and OCR
        if content_type == ContentType.PDF:
            try:
                ocr_content = self._extract_pdf_with_ocr(raw_content)
                ocr_confidence = self._calculate_extraction_confidence(ocr_content, "ocr")
                extraction_results.append({
                    'content': ocr_content,
                    'confidence': ocr_confidence,
                    'method': 'ocr'
                })
            except Exception as e:
                logger.warning(f"OCR extraction failed: {e}")

        # Return best result
        if extraction_results:
            best_result = max(extraction_results, key=lambda x: x['confidence'])
            return (
                f"<BINARY_CONTENT_{content_type.upper()}_SIZE_{len(raw_content)}>",
                best_result['content']
            ), best_result['confidence'], best_result['method']
        else:
            raise ContentExtractionError("All extraction methods failed")

    def _calculate_extraction_confidence(self, content: str, method: str) -> float:
        """Calculate confidence score for extracted content"""
        if not content or len(content) < 10:
            return 0.1

        confidence = 1.0
        content_lower = content.lower()

        # Boost for financial keywords
        financial_keywords = ['annual fee', 'interest rate', 'credit card', 'charges']
        keyword_matches = sum(1 for kw in financial_keywords if kw in content_lower)
        confidence += keyword_matches * 0.1

        # Penalize short content (likely OCR failures)
        if len(content) < 100:
            confidence *= 0.4
        elif len(content) < 500:
            confidence *= 0.7

        # Penalize OCR-based extractions
        if method == "ocr":
            confidence *= 0.8

        # Boost structured content
        if any(marker in content_lower for marker in ['table', '|', 'tk.', '%']):
            confidence *= 1.2

        return min(confidence, 1.0)
```

### Phase 4: Monitoring & Quality Assurance (Week 7-8)

#### 4.1 Data Quality Dashboard

**Quality Metrics Model:**
```python
# Create banks/models.py additions
class ExtractionQualityMetrics(models.Model):
    """Track extraction quality metrics"""

    bank = models.ForeignKey(Bank, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)

    # Success rates
    total_extractions = models.PositiveIntegerField(default=0)
    successful_extractions = models.PositiveIntegerField(default=0)
    annual_fee_extracted = models.PositiveIntegerField(default=0)
    interest_rate_extracted = models.PositiveIntegerField(default=0)

    # Average confidence
    avg_confidence = models.FloatField(null=True, blank=True)

    # Method breakdown
    pdf_text_count = models.PositiveIntegerField(default=0)
    ocr_count = models.PositiveIntegerField(default=0)
    webpage_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ['bank', 'date']

# Create banks/services/quality_metrics.py
class QualityMetricsService:

    @staticmethod
    def update_daily_metrics(bank_id: int):
        """Update daily quality metrics for a bank"""
        today = timezone.now().date()

        # Get today's crawled content
        today_content = CrawledContent.objects.filter(
            data_source__bank_id=bank_id,
            crawled_at__date=today
        )

        # Calculate metrics
        metrics = {
            'total_extractions': today_content.count(),
            'successful_extractions': today_content.filter(
                processing_status=ProcessingStatus.COMPLETED
            ).count(),
            'annual_fee_extracted': today_content.filter(
                parsed_json__annual_fee__isnull=False
            ).count(),
            'interest_rate_extracted': today_content.filter(
                parsed_json__interest_rate_apr__isnull=False
            ).count(),
            'avg_confidence': today_content.aggregate(
                avg=models.Avg('extraction_confidence')
            )['avg'],
        }

        # Update or create metrics
        ExtractionQualityMetrics.objects.update_or_create(
            bank_id=bank_id,
            date=today,
            defaults=metrics
        )
```

#### 4.2 Automated Quality Checks

**Quality Check Tasks:**
```python
# Update banks/tasks.py
@shared_task
def validate_extraction_quality():
    """Daily task to validate extraction quality"""

    # Get recent crawled content without quality validation
    recent_content = CrawledContent.objects.filter(
        extraction_confidence__isnull=True,
        crawled_at__gte=timezone.now() - timedelta(days=1)
    )

    for content in recent_content:
        try:
            confidence, issues = ExtractionQualityValidator.validate_extraction_quality(content)

            content.extraction_confidence = confidence
            content.missing_critical_fields = issues
            content.needs_manual_review = confidence < 0.5 or len(issues) > 1
            content.save()

            # Add to review queue if needed
            if content.needs_manual_review:
                ReviewQueue.add_for_review(content, "low_confidence_extraction")

        except Exception as e:
            logger.error(f"Quality validation failed for content {content.id}: {e}")

@shared_task
def generate_quality_reports():
    """Weekly task to generate quality reports"""

    for bank in Bank.objects.filter(is_active=True):
        # Generate weekly quality summary
        weekly_summary = QualityMetricsService.generate_weekly_summary(bank.id)

        # Send alerts for low quality banks
        if weekly_summary['success_rate'] < 0.7:
            send_quality_alert(bank, weekly_summary)
```

#### 4.3 Manual Review Queue

**Review Queue System:**
```python
# Create banks/models.py additions
class ReviewQueue(models.Model):
    """Queue for manual review of failed extractions"""

    crawled_content = models.OneToOneField(
        CrawledContent,
        on_delete=models.CASCADE,
        related_name='review_task'
    )
    reason = models.CharField(max_length=100)
    priority = models.CharField(
        max_length=20,
        choices=[('low', 'Low'), ('normal', 'Normal'), ('high', 'High')],
        default='normal'
    )
    assigned_to = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled')
        ],
        default='pending'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-priority', 'created_at']

# Create banks/services/review_queue.py
class ReviewQueueService:

    @staticmethod
    def add_for_review(crawled_content, reason, priority='normal'):
        """Add content to manual review queue"""
        ReviewQueue.objects.get_or_create(
            crawled_content=crawled_content,
            defaults={
                'reason': reason,
                'priority': priority
            }
        )

        # Send notification for high priority items
        if priority == 'high':
            send_review_notification(crawled_content, reason)

    @staticmethod
    def get_review_dashboard_data():
        """Get data for review dashboard"""
        return {
            'pending_count': ReviewQueue.objects.filter(status='pending').count(),
            'high_priority_count': ReviewQueue.objects.filter(
                status='pending', priority='high'
            ).count(),
            'avg_resolution_time': ReviewQueue.objects.filter(
                status='completed'
            ).aggregate(
                avg_time=models.Avg(
                    models.F('completed_at') - models.F('created_at')
                )
            )['avg_time'],
        }
```

### Phase 5: Long-term Improvements (Month 2-3)

#### 5.1 Machine Learning Enhancement

**Custom NER Model Training:**
```python
# Future implementation: banks/ml/ner_trainer.py
class FinancialNERTrainer:
    """Train custom NER models for financial document parsing"""

    def train_model(self, training_data):
        """Train spaCy NER model on financial documents"""
        # Implementation for training custom financial entity recognition
        pass

    def extract_entities(self, text):
        """Extract financial entities using trained model"""
        # Implementation for entity extraction
        pass
```

#### 5.2 Document Type Classification

**Document Classifier:**
```python
# Future implementation: banks/services/document_classifier.py
class DocumentTypeClassifier:
    """Automatically classify and route document types"""

    def classify_document(self, content: str, url: str):
        """Classify document type and suggest best extraction strategy"""
        # Implementation for document classification
        pass
```

## 📅 Implementation Timeline

### Week 1: Database Schema & Silent Fix
- [ ] Update CreditCard model to allow NULL values
- [ ] Create and run database migrations
- [ ] Update validator to preserve NULL instead of defaulting to 0
- [ ] Test with existing data

### Week 2: Quality Tracking Infrastructure
- [ ] Add quality fields to CrawledContent model
- [ ] Implement ExtractionQualityValidator
- [ ] Create quality metrics models
- [ ] Add quality validation to crawler pipeline

### Week 3: Multi-Pass LLM Enhancement
- [ ] Implement multi-pass extraction in LLMContentParser
- [ ] Create focused extraction for critical fields
- [ ] Add extraction result merging logic
- [ ] Test with problematic bank documents

### Week 4: Bank-Specific Prompts
- [ ] Create bank-specific prompt templates
- [ ] Implement bank detection and prompt selection
- [ ] Test prompts with different bank document types
- [ ] Fine-tune prompts based on results

### Week 5: Enhanced Content Extraction
- [ ] Implement multi-source validation in ContentExtractor
- [ ] Add extraction confidence scoring
- [ ] Enhance OCR fallback mechanisms
- [ ] Test with various document types

### Week 6: Content Quality Validation
- [ ] Implement comprehensive content quality checks
- [ ] Add extraction method tracking
- [ ] Create confidence scoring algorithms
- [ ] Test quality scoring accuracy

### Week 7: Monitoring Dashboard
- [ ] Create quality metrics tracking
- [ ] Implement daily quality validation tasks
- [ ] Build quality dashboard views
- [ ] Set up quality alerts

### Week 8: Review Queue System
- [ ] Implement manual review queue
- [ ] Create review dashboard
- [ ] Set up review notifications
- [ ] Train team on review process

## 🎯 Success Metrics

### Primary KPIs:
- **Field Completeness**: >90% for annual_fee and interest_rate_apr
- **Data Accuracy**: >95% accuracy for extracted numerical values
- **Extraction Confidence**: Average confidence >0.8
- **Manual Review Rate**: <10% of extractions requiring manual review

### Secondary KPIs:
- **Processing Time**: <2 minutes per document
- **Bank Coverage**: All 50+ Bangladeshi banks with consistent extraction
- **Error Rate**: <5% extraction failures
- **Alert Response Time**: <4 hours for critical issues

## 🚨 Risk Mitigation

### High Risk Items:
1. **Database Migration**: Test thoroughly in staging
2. **LLM API Limits**: Implement proper rate limiting and fallbacks
3. **OCR Dependencies**: Ensure pytesseract/tesseract properly installed
4. **Manual Review Load**: Start with automated reviews before adding manual queue

### Contingency Plans:
- **Rollback Plan**: Keep original extraction logic as fallback
- **Data Recovery**: Maintain backup of original crawled data
- **API Failures**: Multiple LLM provider fallbacks
- **Performance Issues**: Implement extraction queuing if needed

---

*This improvement plan should be reviewed and updated quarterly based on implementation results and emerging needs.*
