class GeminiPricePredictor:
    def predict_price(self, job_details):
        prompt = f"""
        Historical job pricing context:
        {self._get_pricing_history()}
        
        New job details:
        Origin: {job_details.origin}
        Destination: {job_details.destination}
        Distance: {job_details.distance} miles
        Day of week: {job_details.day}
        Time of day: {job_details.time}
        Special requirements: {job_details.requirements}
        
        Based on historical pricing patterns, suggest an appropriate price for this job.
        """
        
        response = self.model.generate_content(prompt)
        return response.text

    def record_pricing_feedback(self, job_id, suggested_price, actual_price, profit_margin, customer_accepted):
        feedback = PricingFeedback(
            job_id=job_id,
            suggested_price=suggested_price,
            actual_price=actual_price,
            profit_margin=profit_margin,
            customer_accepted=customer_accepted,
            notes="Additional context about why price worked/didn't work"
        )
        self.pricing_history.append(feedback)