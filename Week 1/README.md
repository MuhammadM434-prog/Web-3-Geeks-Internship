# Adult Income Classification — Final Week 1 Project

## 1. Project Objective

This project predicts whether an adult earns more than **$50K**. The model is intended to support prioritization of potential high-income prospects.

The final production solution uses a calibrated **Logistic Regression** classifier with a classification threshold of **0.30**, selected to improve the F1-score and recall for the chosen business objective.

---

## 2. Dataset Description

- **Dataset:** OpenML Adult version 2
- **Task:** Binary classification
- **Target:** Whether annual income is greater than $50K
- **Target encoding:** 0/1
- **Missing-value handling:** `?` values were converted to missing values.

A stratified **80% training/development and 20% untouched test split** was used. The training/development portion was further split for model development and threshold selection.

The final test set remained untouched during model selection and threshold optimization.

---

## 3. Feature Engineering

The project reproduced the following deterministic feature engineering:

- Age buckets
- Part-time employment indicator
- Capital-gain presence indicator
- Log transformation of capital gain
- Higher-education indicator
- Overtime indicator
- Married-status feature

The production wrapper applies the same feature transformation automatically before inference, so preprocessing does not need to be manually repeated when making predictions.

---

## 4. Preprocessing

The saved production workflow handles the required preprocessing and feature engineering as part of the inference pipeline.

The production wrapper accepts raw Adult-style input rows and applies the same transformations used during model development before generating predictions.

This reduces the risk of training-serving skew caused by manually reproducing preprocessing at inference time.

---

## 5. Models Tested

The following models were evaluated:

1. Logistic Regression
2. Random Forest
3. Gradient Boosting

At a default classification threshold of 0.50 on the test set:

- Logistic Regression achieved F1 = **0.6754**
- Gradient Boosting achieved F1 = **0.6839**

The final calibrated Logistic Regression model was selected because threshold optimization on the development set produced the strongest final F1 for the chosen business objective.

---

## 6. Hyperparameter Tuning

Day 4 used a reproducible **5-fold StratifiedKFold randomized search** with **F1 scoring**.

### Selected Logistic Regression configuration

- Regularization: **L1**
- `C`: **3**
- Solver: **liblinear**

The final model was calibrated using sigmoid calibration.

The classification threshold was selected separately using the development data.

### Final classification threshold

**0.30**

The lower threshold was chosen to increase recall and F1 relative to the default 0.50 threshold, accepting some reduction in precision and accuracy.

---

## 7. Final Test Performance

The final model was evaluated on the untouched test set using the selected threshold of 0.30.

| Metric | Final Test Result |
|---|---:|
| Accuracy | **0.8367** |
| Precision | **0.6241** |
| Recall | **0.7990** |
| F1-score | **0.7008** |
| ROC-AUC | **0.9135** |
| PR-AUC | **0.7869** |
| Brier Score | **0.0977** |

### Confusion Matrix

| | Predicted ≤50K | Predicted >50K |
|---|---:|---:|
| **Actual ≤50K** | TN = **6306** | FP = **1125** |
| **Actual >50K** | FN = **470** | TP = **1868** |

The model therefore identifies a relatively large proportion of actual high-income cases, reflected by the **0.7990 recall**.

---

## 8. Diagnostics and Calibration

Learning-curve analysis showed a small train-validation gap that narrowed as training size increased. Both curves flattened near an F1-score of approximately **0.67**, suggesting that the final model did not exhibit severe overfitting.

Sigmoid calibration slightly improved the test Brier score:

- Before calibration: **0.0978**
- After calibration: **0.0977**

Threshold optimization increased recall and F1 while reducing precision and accuracy compared with the default 0.50 threshold.

---

## 9. Important Features and Model Interpretation

Because the final model is Logistic Regression, model behavior was interpreted using its learned coefficients.

The most influential features included:

- **Log_CapitalGain** — the largest positive coefficient
- Capital-gain presence
- Marital-status indicators
- Age
- Occupation indicators
- Country indicators
- Sex indicators

### Interpretation

Positive coefficients increase the model's log-odds of predicting the high-income class, while negative coefficients decrease those log-odds, holding the other model features constant.

Capital-gain-related variables have a particularly strong influence on the prediction. The opposing capital-gain coefficients should be reviewed for redundancy and coefficient stability.

Demographic variables such as sex and other demographic indicators may function as historical proxies. Their coefficients should therefore **not be interpreted causally**.

---

## 10. Error Analysis

The final confusion matrix contains:

- **1,125 false positives**
- **470 false negatives**

For the selected business objective, false negatives are important because they represent actual high-income individuals that the model fails to identify. The threshold of 0.30 was therefore chosen to favor recall and reduce missed positive cases.

The analysis also found weaker performance for:

- Younger adults
- Lower-education groups
- Females

Subgroup recall and calibration should therefore be monitored when the model is used in practice.

---

## 11. Production Readiness

The original Day 4 calibrated artifact was loaded without retraining.

A production wrapper containing the existing feature transformation and fitted model was saved as:

`final_adult_income_production.joblib`

### Inference workflow

The production inference process:

1. Loads the saved `.joblib` artifact.
2. Accepts raw Adult-style input data.
3. Applies the existing feature transformation automatically.
4. Generates prediction probabilities.
5. Applies the selected threshold of **0.30**.
6. Returns the final binary prediction.

No manual preprocessing is required outside the saved production wrapper.

The inference workflow was tested on **10 unseen examples**.

---

## 12. Data Leakage Validation

The train, development, and test split indices were recreated and checked.

The validation confirmed **no overlap between the training, development, and untouched test sets**.

The test set was not used for threshold selection or model fitting.

---

## 13. Saved Artifacts

The main production model artifact is:

`final_adult_income_production.joblib`

The original calibrated Day 4 model artifact was also loaded without retraining as part of the final productionization process.

The Week 1 project notebook contains the validation, diagnostics, interpretation, inference testing, and final reporting workflow.

---

## 14. How to Reproduce the Project

### Environment

The project was developed using Python and common machine-learning/data-science libraries used in the notebook, including:

- Python
- pandas
- NumPy
- scikit-learn
- joblib
- matplotlib

The exact package versions should be taken from the execution environment used for the notebook if strict environment reproduction is required.

### Reproduction steps

1. Open the Week 1 Day 5 notebook.
2. Load the Adult dataset using the same dataset/version used during development.
3. Recreate the deterministic preprocessing and feature-engineering steps.
4. Recreate the stratified training/development/test split.
5. Load the saved Day 4 model configuration/artifact.
6. Run the final validation on the untouched test set.
7. Generate the final metrics, confusion matrix, subgroup analysis, and interpretation plots.
8. Run the production inference tests.
9. Use `final_adult_income_production.joblib` for inference on new raw Adult-style records.

---

## 15. How to Run Inference

A minimal inference workflow is:

```python
import joblib

model = joblib.load("final_adult_income_production.joblib")

# new_data should contain raw Adult-style feature columns.
probability = model.predict_proba(new_data)[:, 1]
prediction = (probability >= 0.30).astype(int)
```

The saved production wrapper is responsible for applying the required feature engineering and preprocessing.

The resulting:

- `probability` is the predicted probability of income > $50K.
- `prediction = 1` means the probability meets or exceeds the selected 0.30 threshold.
- `prediction = 0` means the probability is below 0.30.

---

## 16. Known Limitations

The final model has several limitations:

1. Performance is weaker for younger adults, lower-education groups, and females.
2. Demographic features can act as historical proxies and may raise fairness concerns.
3. Capital-gain-related coefficients should be reviewed for redundancy and stability.
4. The Adult dataset may not represent current income patterns, so performance may degrade under distribution shift.
5. The selected threshold optimizes the chosen F1-oriented objective and may not be optimal under a different business cost structure.
6. Additional input-schema validation should be added around the serving wrapper.
7. Model performance, subgroup recall, calibration, and data drift should be monitored after deployment.

---

## 17. Future Improvements

Potential improvements include:

- Validate an explicit cost-sensitive classification threshold.
- Evaluate the model on newer and more representative data.
- Test coefficient stability across resamples.
- Monitor production data drift.
- Review proxy-sensitive demographic features.
- Add stronger input-schema validation.
- Explore additional feature engineering and alternative models.
- Perform additional subgroup fairness and calibration analysis.

---

## 18. Final Model Summary

**Selected model:** Calibrated Logistic Regression  
**Regularization:** L1  
**C:** 3  
**Solver:** liblinear  
**Classification threshold:** 0.30  
**F1-score:** 0.7008  
**Recall:** 0.7990  
**Precision:** 0.6241  
**Accuracy:** 0.8367  
**ROC-AUC:** 0.9135  
**PR-AUC:** 0.7869  
**Brier Score:** 0.0977  
**Production artifact:** `final_adult_income_production.joblib`
