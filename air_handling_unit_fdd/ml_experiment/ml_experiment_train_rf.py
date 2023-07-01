import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, roc_curve, auc, confusion_matrix
from sklearn.ensemble import RandomForestClassifier
import pickle

# Load data
data = pd.read_csv('../ahu_data/MZVAV-1.csv')
# Convert 'Date' to datetime object
data['Date'] = pd.to_datetime(data['Date'])

# Define features and target
X = data.drop(columns=['Date', 'Fault Detection Ground Truth'])
y = data['Fault Detection Ground Truth']

# Split data
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Define pipeline
pipe = Pipeline([
    ('scaler', StandardScaler()),
    ('rf', RandomForestClassifier())
])

param_grid = {
    'rf__n_estimators': [50, 100, 200],  # Number of trees in the forest
    'rf__max_depth': [None, 5, 10],  # Maximum depth of each tree
    'rf__min_samples_split': [2, 5, 10],  # Minimum number of samples required to split an internal node
    'rf__min_samples_leaf': [1, 2, 4],  # Minimum number of samples required to be at a leaf node
    'rf__max_features': ['auto', 'sqrt', 'log2']  # Number of features to consider when looking for the best split
}


# Perform grid search
clf = GridSearchCV(pipe, param_grid, cv=5)
clf.fit(X_train, y_train)

# Print best parameters and score
print(f"Best parameters: {clf.best_params_}")
print(f"Best score: {clf.best_score_}")

# Evaluate on test set
y_pred = clf.predict(X_test)
print(f"Classification report:")
print(classification_report(y_test, y_pred))

# Plot confusion matrix
cm = confusion_matrix(y_test, y_pred)
plt.imshow(cm, cmap=plt.cm.Blues)
plt.title('Confusion Matrix')
plt.colorbar()
classes = ['class_0', 'class_1']  # Replace with your class labels
tick_marks = range(len(classes))
plt.xticks(tick_marks, classes, rotation=45)
plt.yticks(tick_marks, classes)
plt.xlabel('Predicted Label')
plt.ylabel('True Label')
for i in range(len(classes)):
    for j in range(len(classes)):
        plt.text(j, i, format(cm[i, j], 'd'), ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "black")
#plt.show()

# Plot ROC curve
y_prob = clf.predict_proba(X_test)[:, 1]
fpr, tpr, _ = roc_curve(y_test, y_prob)
roc_auc = auc(fpr, tpr)

plt.figure()
plt.plot(fpr, tpr, label='ROC curve (area = %0.2f)' % roc_auc)
plt.plot([0, 1], [0, 1], 'k--')
plt.xlim([0.0, 1.0])
plt.ylim([0.0, 1.05])
plt.xlabel('False Positive Rate')
plt.ylabel('True Positive Rate')
plt.title('Receiver Operating Characteristic')
plt.legend(loc="lower right")
plt.savefig('./ahu_data/ml_training_results/roc_curve_rf_only.png')

# Save the best model
with open('best_model_rf.pkl', 'wb') as f:
    pickle.dump(clf.best_estimator_, f)
