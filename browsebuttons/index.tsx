import React, { useState, useEffect, CSSProperties, FormEvent } from 'react';
import ReactDOM from 'react-dom/client';

// The base URL of your Python Flask API server
const API_BASE_URL = 'http://localhost:8765';

// --- Color definitions ---
const BASE_COLORS: { [key: string]: string } = {
  'K':'#000000', 'R':'#FF0000', 'G':'#00FF00', 'O':'#FF9900',
  'B':'#0066CC', 'Y':'#FFFF00', 'U':'#800080', 'S':'#00FFFF',
  'E':'#808080', 'W':'#FFFFFF', 'L':'#FDF6E3', 'P':'#FFC0CB'
};

// --- Helper functions ---
const dimColor = (hex: string): string => {
  try {
    const r = Math.floor(parseInt(hex.slice(1, 3), 16) / 2).toString(16).padStart(2, '0');
    const g = Math.floor(parseInt(hex.slice(3, 5), 16) / 2).toString(16).padStart(2, '0');
    const b = Math.floor(parseInt(hex.slice(5, 7), 16) / 2).toString(16).padStart(2, '0');
    return `#${r}${g}${b}`;
  } catch (e) { return hex; }
};

const getColorFromFlags = (flags: string): string => {
  const upperFlags = flags.toUpperCase();
  const colorPriority = ['R', 'G', 'O', 'B', 'Y', 'U', 'S', 'E', 'W', 'L', 'P'];
  let baseColor = BASE_COLORS['K'];
  for (const color of colorPriority) {
    if (upperFlags.includes(color)) { baseColor = BASE_COLORS[color]; break; }
  }
  if (upperFlags.includes('D')) { return dimColor(baseColor); }
  return baseColor;
};

// --- Interfaces ---
interface ButtonConfig {
  id: number;
  label: string;
  command: string;
  flags: string;
  monitor_keyword: string;
}
interface SessionVars {
  [key: string]: string;
}

// --- Styles ---
const styles: { [key: string]: CSSProperties } = {
  container: { fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif', maxWidth: '900px', margin: '0 auto', padding: '20px', color: '#333', backgroundColor: '#f8f9fa' },
  header: { borderBottom: '1px solid #dee2e6', paddingBottom: '20px', marginBottom: '30px', textAlign: 'center' },
  headerH1: { color: '#212529', margin: '0 0 10px 0' },
  section: { marginBottom: '25px', padding: '25px', backgroundColor: '#ffffff', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.07)' },
  sectionHeading: { marginTop: '0', marginBottom: '20px', color: '#343a40', borderBottom: '1px solid #e9ecef', paddingBottom: '10px' },
  form: { display: 'flex', flexDirection: 'column', gap: '15px' },
  inputGroup: { display: 'flex', flexDirection: 'column' },
  label: { marginBottom: '5px', fontWeight: 'bold', color: '#495057' },
  input: { padding: '12px', border: '1px solid #ced4da', borderRadius: '4px', fontSize: '1em', backgroundColor: '#fff' },
  textarea: { padding: '12px', border: '1px solid #ced4da', borderRadius: '4px', fontSize: '1em', minHeight: '80px', resize: 'vertical', backgroundColor: '#fff' },
  button: { padding: '12px 18px', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '1em', fontWeight: 'bold', transition: 'background-color 0.2s ease' },
  primaryButton: { backgroundColor: '#007aff', color: 'white' },
  secondaryButton: { backgroundColor: '#6c757d', color: 'white' },
  dangerButton: { backgroundColor: '#dc3545', color: 'white' },
  buttonList: { listStyle: 'none', padding: '0' },
  buttonListItem: { backgroundColor: '#fff', padding: '10px 20px', border: '1px solid #e9ecef', borderRadius: '6px', marginBottom: '8px', display: 'flex', flexDirection: 'column', gap: '8px' },
  buttonListItemHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  buttonLabelContainer: { display: 'flex', alignItems: 'center', gap: '12px' },
  colorSwatch: { width: '18px', height: '18px', borderRadius: '4px', border: '1px solid #ccc', flexShrink: 0 },
  buttonLabel: { fontWeight: 'bold', fontSize: '1.2em', color: '#007aff' },
  buttonActions: { display: 'flex', gap: '10px' },
  buttonDetails: { fontSize: '0.9em', color: '#495057', wordBreak: 'break-all', paddingLeft: '30px' },
  code: { fontFamily: 'monospace', backgroundColor: '#e9ecef', color: '#212529', padding: '3px 6px', borderRadius: '3px' },
  variableDisplay: { marginTop: '8px', paddingLeft: '30px' },
  variableTag: { display: 'inline-block', backgroundColor: '#f0f0f0', color: '#333', padding: '4px 8px', borderRadius: '4px', marginRight: '8px', marginBottom: '8px', fontSize: '0.85em' },
  modalOverlay: { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0, 0, 0, 0.6)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 },
  modalContent: { backgroundColor: 'white', padding: '30px', borderRadius: '8px', boxShadow: '0 5px 15px rgba(0,0,0,0.3)', width: '90%', maxWidth: '500px' },
  modalActions: { display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '20px' },
  // --- MODIFIED STYLES for Flag Legend ---
  flagLegend: {
    marginTop: '20px',
    padding: '12px', // Reduced padding
    border: '1px solid #e9ecef',
    borderRadius: '6px',
    backgroundColor: '#f8f9fa',
  },
  flagLegendTitle: {
    margin: '0 0 8px 0', // Reduced margin
    fontSize: '0.9em', // Reduced font size
    fontWeight: 'bold',
  },
  flagLegendList: {
    margin: '0',
    paddingLeft: '18px', // Reduced padding
    listStyle: 'disc',
    display: 'grid', // Use grid for better alignment
    gridTemplateColumns: '1fr 1fr', // Two columns
    gap: '0 15px', // Spacing between columns
  },
  flagLegendItem: {
    marginBottom: '4px', // Reduced margin
    fontSize: '0.85em', // Reduced font size
  },
  noButtonsMessage: { textAlign: 'center', color: '#6c757d', padding: '20px', fontSize: '1.1em' },
  errorMessage: { textAlign: 'center', color: '#721c24', backgroundColor: '#f8d7da', padding: '15px', borderRadius: '4px', border: '1px solid #f5c6cb', marginBottom: '20px' },
};


const FlagLegend: React.FC = () => (
  <div style={styles.flagLegend}>
    <h4 style={styles.flagLegendTitle}>Flag Legend</h4>
    <ul style={styles.flagLegendList}>
      <li style={styles.flagLegendItem}><code>@</code> - Device button</li>
      <li style={styles.flagLegendItem}><code>!</code> - Monitor state</li>
      <li style={styles.flagLegendItem}><code>N</code> - New window</li>
      <li style={styles.flagLegendItem}><code>V</code> - Edit Variables</li>
      <li style={styles.flagLegendItem}><code>#</code> - Numeric Mode</li>
      <li style={styles.flagLegendItem}><code>K</code> - Force Local</li>
      <li style={styles.flagLegendItem}><code>M</code> - Mobile SSH</li>
      <li style={styles.flagLegendItem}><code>D</code> - Dim Color</li>
      <li style={styles.flagLegendItem}><code>T</code> - Toggle button</li>
      <li style={styles.flagLegendItem}><code>R,G,B..</code> - Colors</li>
    </ul>
  </div>
);

const VariableDisplay: React.FC<{ command: string; sessionVars: SessionVars }> = ({ command, sessionVars }) => {
  const varRegex = /\{\{([^:}]+):?([^}]*)?\}\}/g;
  const variables = [];
  let match;
  while ((match = varRegex.exec(command)) !== null) {
    const varName = match[1];
    const currentValue = sessionVars[varName];
    if (varName && currentValue !== undefined) { variables.push({ name: varName, value: currentValue }); }
  }
  if (variables.length === 0) { return null; }
  return (
    <div style={styles.variableDisplay}>
      {variables.map(v => (
        <span key={v.name} style={styles.variableTag}><code style={{fontWeight: 'bold'}}>{v.name}</code> = <code>{v.value}</code></span>
      ))}
    </div>
  );
};

const App: React.FC = () => {
  const [buttons, setButtons] = useState<ButtonConfig[]>([]);
  const [sessionVars, setSessionVars] = useState<SessionVars>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState('');
  const [newCommand, setNewCommand] = useState('');
  const [newFlags, setNewFlags] = useState('');
  const [newMonitorKeyword, setNewMonitorKeyword] = useState('');
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingButton, setEditingButton] = useState<ButtonConfig | null>(null);
  const [editLabel, setEditLabel] = useState('');
  const [editCommand, setEditCommand] = useState('');
  const [editFlags, setEditFlags] = useState('');
  const [editMonitorKeyword, setEditMonitorKeyword] = useState('');

  useEffect(() => {
    const fetchButtons = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/buttons`);
        if (!response.ok) throw new Error(`Failed to connect to driver. Is it running? (Status: ${response.status})`);
        const data = await response.json();
        setButtons(data.buttons); setSessionVars(data.variables); setApiError(null);
      } catch (error) { console.error("Error fetching buttons:", error); setApiError(String(error)); }
    };
    fetchButtons();
  }, []);

  const handleAddButton = async (e: FormEvent) => {
    e.preventDefault();
    if (!newLabel.trim()) { alert('Label is required.'); return; }
    const newButtonData = { label: newLabel, command: newCommand, flags: newFlags, monitor_keyword: newMonitorKeyword };
    try {
      const response = await fetch(`${API_BASE_URL}/api/buttons`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newButtonData) });
      if (!response.ok) throw new Error('Failed to add button.');
      const responseData = await response.json();
      setButtons([...buttons, responseData.button]);
      setNewLabel(''); setNewCommand(''); setNewFlags(''); setNewMonitorKeyword('');
    } catch (error) { console.error("Error adding button:", error); alert("Error: Could not add the button."); }
  };

  const handleDeleteButton = async (id: number) => {
    if (window.confirm('Are you sure you want to delete this button configuration?')) {
      try {
        const response = await fetch(`${API_BASE_URL}/api/buttons/${id}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete button.');
        setButtons(buttons.filter(button => button.id !== id));
      } catch (error) { console.error("Error deleting button:", error); alert("Error: Could not delete the button."); }
    }
  };

  const handleSaveEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editingButton || !editLabel.trim()) { alert('Label is required.'); return; }
    const updatedButtonData = { label: editLabel, command: editCommand, flags: editFlags, monitor_keyword: editMonitorKeyword };
    try {
      const response = await fetch(`${API_BASE_URL}/api/buttons/${editingButton.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updatedButtonData) });
      if (!response.ok) throw new Error('Failed to save changes.');
      setButtons(buttons.map(button => button.id === editingButton.id ? { ...editingButton, ...updatedButtonData } : button));
      closeEditModal();
    } catch (error) { console.error("Error saving button:", error); alert("Error: Could not save changes."); }
  };

  const openEditModal = (button: ButtonConfig) => {
    setEditingButton(button); setEditLabel(button.label); setEditCommand(button.command);
    setEditFlags(button.flags); setEditMonitorKeyword(button.monitor_keyword || ''); setIsEditModalOpen(true);
  };
  const closeEditModal = () => { setIsEditModalOpen(false); setEditingButton(null); };

  return (
    <div style={styles.container}>
      <header style={{...styles.header, paddingTop: '10px' }}><h1>StreamDeck Live Controller</h1><p>Manage button configurations for your running StreamDeck driver.</p></header>
      {apiError && <div style={styles.errorMessage} role="alert"><strong>Connection Error:</strong> {apiError}</div>}
      <section style={styles.section}>
        <h2>Add New Button</h2>
        <form onSubmit={handleAddButton} style={styles.form}>
          <div style={styles.inputGroup}><label htmlFor="newLabel" style={styles.label}>Label:</label><input id="newLabel" type="text" value={newLabel} onChange={e => setNewLabel(e.target.value)} style={styles.input} required /></div>
          <div style={styles.inputGroup}><label htmlFor="newCommand" style={styles.label}>Command:</label><textarea id="newCommand" value={newCommand} onChange={e => setNewCommand(e.target.value)} style={styles.textarea} rows={3} /></div>
          <div style={styles.inputGroup}><label htmlFor="newFlags" style={styles.label}>Flags:</label><input id="newFlags" type="text" value={newFlags} onChange={e => setNewFlags(e.target.value)} style={styles.input} placeholder="e.g., R16@!, GD#N, B12VT" /></div>
          <div style={styles.inputGroup}><label htmlFor="newMonitorKeyword" style={styles.label}>Monitor Keyword:</label><input id="newMonitorKeyword" type="text" value={newMonitorKeyword} onChange={e => setNewMonitorKeyword(e.target.value)} style={styles.input} placeholder="e.g., my-long-running-process" /></div>
          <button type="submit" style={{ ...styles.button, ...styles.primaryButton }}>Add Button</button>
        </form>
      </section>
      <section style={styles.section}>
        <h2>Configured Buttons ({buttons.length})</h2>
        {buttons.length === 0 && !apiError ? ( <p style={styles.noButtonsMessage}>No buttons loaded. Check driver or add one above.</p> ) : (
          <ul style={styles.buttonList}>
            {buttons.map(button => (
              <li key={button.id} style={styles.buttonListItem}>
                <div style={styles.buttonListItemHeader}>
                  <div style={styles.buttonLabelContainer}>
                    <span style={{...styles.colorSwatch, backgroundColor: getColorFromFlags(button.flags)}}></span>
                    <strong style={styles.buttonLabel}>{button.label}</strong>
                  </div>
                  <div style={styles.buttonActions}>
                    <button onClick={() => openEditModal(button)} style={{ ...styles.button, ...styles.secondaryButton }}>Edit</button>
                    <button onClick={() => handleDeleteButton(button.id)} style={{ ...styles.button, ...styles.dangerButton }}>Delete</button>
                  </div>
                </div>
                <div style={styles.buttonDetails}>
                  <p><strong>Command:</strong> <code style={styles.code}>{button.command || '(empty)'}</code></p>
                  <p><strong>Flags:</strong> <code style={styles.code}>{button.flags || '(none)'}</code></p>
                  <p><strong>Monitor Keyword:</strong> <code style={styles.code}>{button.monitor_keyword || '(none)'}</code></p>
                </div>
                <VariableDisplay command={button.command} sessionVars={sessionVars} />
              </li>
            ))}
          </ul>
        )}
      </section>
      {isEditModalOpen && editingButton && (
        <div style={styles.modalOverlay}>
          <div style={styles.modalContent}>
            <h3>Edit Button: {editingButton.label}</h3>
            <form onSubmit={handleSaveEdit} style={styles.form}>
              <div style={styles.inputGroup}><label htmlFor="editLabel" style={styles.label}>Label:</label><input id="editLabel" type="text" value={editLabel} onChange={e => setEditLabel(e.target.value)} style={styles.input} required /></div>
              <div style={styles.inputGroup}><label htmlFor="editCommand" style={styles.label}>Command:</label><textarea id="editCommand" value={editCommand} onChange={e => setEditCommand(e.target.value)} style={styles.textarea} rows={3} /></div>
              <div style={styles.inputGroup}><label htmlFor="editFlags" style={styles.label}>Flags:</label><input id="editFlags" type="text" value={editFlags} onChange={e => setEditFlags(e.target.value)} style={styles.input} /></div>
              <div style={styles.inputGroup}><label htmlFor="editMonitorKeyword" style={styles.label}>Monitor Keyword:</label><input id="editMonitorKeyword" type="text" value={editMonitorKeyword} onChange={e => setEditMonitorKeyword(e.target.value)} style={styles.input} /></div>
              <FlagLegend />
              <div style={styles.modalActions}>
                <button type="button" onClick={closeEditModal} style={{ ...styles.button, ...styles.secondaryButton }}>Cancel</button>
                <button type="submit" style={{ ...styles.button, ...styles.primaryButton }}>Save Changes</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

const rootElement = document.getElementById('root');
if (rootElement) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(<React.StrictMode><App /></React.StrictMode>);
} else {
  console.error('Failed to find the root element.');
}