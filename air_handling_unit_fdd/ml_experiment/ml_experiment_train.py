import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, roc_curve, auc, confusion_matrix
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
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

# Models to test
models = [
    ('lr', LogisticRegression()),
    ('rf', RandomForestClassifier()),
    ('svm', SVC(probability=True)),
    ('mlp', MLPClassifier(max_iter=1000))  # Increase max_iter for larger datasets
]

# Param grids for GridSearchCV
param_grids = {
    'lr': {'lr__C': [0.1, 1, 10]},
    'rf': {'rf__n_estimators': [50, 100, 200]},
    'svm': {'svm__C': [0.1, 1, 10]},
    'mlp': {'mlp__hidden_layer_sizes': [(50,), (100,), (200,)]}
}

best_score = 0
best_model = None

# Standardize features
scaler = StandardScaler()

for model_name, model in models:
    pipe = Pipeline(steps=[('scaler', scaler), (model_name, model)])

    clf = GridSearchCV(pipe, param_grids[model_name], cv=5)
    clf.fit(X_train, y_train)
    
    print(f"Best parameters for {model_name}: {clf.best_params_}")
    
    # Evaluate on test set
    y_pred = clf.predict(X_test)
    print(f"Classification report for {model_name}:")
    print(classification_report(y_test, y_pred))
    
    # Plot confusion matrix
    cm = confusion_matrix(y_test, y_pred)
    plt.imshow(cm, cmap=plt.cm.Blues)
    plt.title(f'Confusion Matrix for {model_name}')
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
    
    # ROC curve
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
    plt.title(f'Receiver Operating Characteristic for {model_name}')
    plt.legend(loc="lower right")
    plt.savefig(f'./ahu_data/ml_training_results/{model_name}.png')

    # Save if better than current best model
    if clf.best_score_ > best_score:
        best_score = clf.best_score_
        best_model = clf.best_estimator_

# Save the best model
with open(f'best_model.pkl', 'wb') as f:
    pickle.dump(best_model, f)
