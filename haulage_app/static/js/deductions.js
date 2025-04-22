document.addEventListener('DOMContentLoaded', function() {
    // Initialize deduction inputs
    document.querySelectorAll('input[id^="deductions_"]').forEach(input => {
        // Add event listener for input changes
        input.addEventListener('input', function() {
            const driverId = this.id.split('_')[1];
            updateDriverBasicWage(driverId, this.value);
        });
        
        // Trigger on initial load
        updateDriverBasicWage(input.id.split('_')[1], input.value);
    });
    
    // Initialize extras calculation for all drivers
    document.querySelectorAll('[id^="weekly_bonus_threshold_"]').forEach(input => {
        const driverId = input.id.split('_').pop();
        updateExtras(driverId);
        
        // Add event listeners to bonus inputs
        input.addEventListener('input', function() {
            updateExtras(driverId);
            updateDriverTotals(driverId);
        });
        
        const dailyBonusInput = document.getElementById(`total_daily_bonus_${driverId}`);
        if (dailyBonusInput) {
            dailyBonusInput.addEventListener('input', function() {
                updateExtras(driverId);
                updateDriverTotals(driverId);
            });
        }
    });
    
    function updateDriverBasicWage(driverId, deductionValue) {
        const deductionDisplayElement = document.querySelector(`#deductions_display_${driverId}`);
    
        // Convert to float and handle NaN - multiply by 100 to convert pounds to pence
        const deductionPence = (parseFloat(deductionValue) || 0) * 100;
        
        const basicWageElement = document.querySelector(`#basic_wage_${driverId}`);
        const originalBasicWageElement = document.querySelector(`#original_basic_wage_${driverId}`);
        
        if (basicWageElement && originalBasicWageElement) {
            // Get the original basic wage value in pence (without deductions)
            const originalBasicWagePence = parseInt(originalBasicWageElement.value) * 100 || 0;
            
            // Calculate new basic wage value after deduction (in pence)
            const newBasicWagePence = Math.max(0, originalBasicWagePence - deductionPence);
            
            // Convert back to pounds with 2 decimal places for display
            const currencySymbol = basicWageElement.textContent.trim().charAt(0);
            basicWageElement.textContent = `${currencySymbol}${(newBasicWagePence / 100).toFixed(2)}`;

            deductionDisplayElement.textContent = `${currencySymbol}${(deductionPence / 100).toFixed(2)}`;
            
            // Update any related totals
            updateDriverTotals(driverId);
        }
    }

    function updateExtras(driverId) {
        // Get the values
        const totalEarned = parseFloat(document.getElementById(`total_earned_${driverId}`).value) || 0;
        const dailyBonus = parseFloat(document.getElementById(`total_daily_bonus_${driverId}`).value) || 0;
        let weeklyBonus = parseFloat(document.getElementById(`weekly_bonus_display_${driverId}`).value) || 0;
        const weeklyBonusThreshold = parseFloat(document.getElementById(`weekly_bonus_threshold_${driverId}`).value) || 0;
        const weeklyBonusPercentage = document.getElementById(`weekly_bonus_percentage_${driverId}`).value || 0;

        if(totalEarned > weeklyBonusThreshold) {
            weeklyBonus = (totalEarned - weeklyBonusThreshold) * weeklyBonusPercentage
        }
        else {
            weeklyBonus = 0
        }
        // Calculate and format the sum as currency          
        const extras = dailyBonus + weeklyBonus;
        const formattedExtras = new Intl.NumberFormat('en-GB', { 
            style: 'currency',
            currency: 'GBP'
        }).format(extras);
        const formattedWeeklyBonus = new Intl.NumberFormat('en-GB', {
            style: 'currency',
            currency: 'GBP'
        }).format(weeklyBonus);

        // Update the extras display
        document.getElementById(`extras_${driverId}`).textContent = formattedExtras;
        document.querySelector(`#weekly_bonus_display_${driverId}`).textContent = formattedWeeklyBonus;
    }

    function updateDriverTotals(driverId) {
        // Find all relevant elements
        const elements = {
            earned: document.querySelector(`#total_earned_${driverId}`),
            extras: document.querySelector(`#extras_${driverId}`),
            overnights: document.querySelector(`#total_overnight_${driverId}`),
            basicWage: document.querySelector(`#basic_wage_${driverId}`),
            total: document.querySelector(`#total_${driverId}`),
        };

        if (Object.values(elements).every(el => el)) {
            // Extract currency symbol and values in pence
            const currencySymbol = elements.earned.textContent.trim().charAt(0);
            const values = {
                earnedPence: Math.round(parseFloat(elements.earned.textContent.substring(1)) * 100) || 0,
                extrasPence: Math.round(parseFloat(elements.extras.textContent.substring(1)) * 100) || 0,
                overnightsPence: Math.round(parseFloat(elements.overnights.textContent.substring(1)) * 100) || 0,
                basicWagePence: Math.round(parseFloat(elements.basicWage.textContent.substring(1)) * 100) || 0
            };

            // Calculate total in pence and convert to pounds for display
            const totalPence = Object.values(values).reduce((sum, val) => sum + val, 0);
            elements.total.textContent = `${currencySymbol}${(totalPence / 100).toFixed(2)}`;
        }
    }
});