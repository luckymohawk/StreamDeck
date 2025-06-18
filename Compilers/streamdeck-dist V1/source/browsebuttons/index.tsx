import React, { useState, useEffect, CSSProperties, FormEvent } from 'react';
import ReactDOM from 'react-dom/client';

// The base URL of the Python Flask API server.
const API_BASE_URL = 'http://localhost:8765';

// Color definitions.
const BASE_COLORS: { [key: string]: string } = {
  'R': '#FF0000', 'G': '#00FF00', 'B': '#0066CC',
  'O': '#FF9900', 'Y': '#FFFF00', 'P': '#800080',
  'S': '#C0C0C0', 'F': '#FF00FF', 'W': '#FFFFFF',
  'L': '#FDF6E3'
};

// Helper functions.
const dimColor = (hex: string): string => {
  try {
    const r = Math.floor(parseInt(hex.slice(1, 3), 16) / 2).toString(16).padStart(2, '0');
    const g = Math.floor(parseInt(hex.slice(3, 5), 16) / 2).toString(16).padStart(2, '0');
    const b = Math.floor(parseInt(hex.slice(5, 7), 16) / 2).toString(16).padStart(2, '0');
    return `#${r}${g}${b}`;
  } catch (e) { return hex; }
};

const getColorFromFlags = (flags: string): string => {
  const upperFlags = (flags || '').toUpperCase();
  const colorPriority = Object.keys(BASE_COLORS);
  let baseColor = '#000000';
  for (const color of colorPriority) {
    if (upperFlags.includes(color)) { baseColor = BASE_COLORS[color]; break; }
  }
  if (upperFlags.includes('D')) { return dimColor(baseColor); }
  return baseColor;
};

// Interfaces.
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

// Styles.
const styles: { [key: string]: CSSProperties } = {
  container: { fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif', maxWidth: '800px', margin: '0 auto', padding: '10px', color: '#333', backgroundColor: '#f0f2f5' },
  header: { borderBottom: '1px solid #dcdcdc', paddingBottom: '10px', marginBottom: '15px', textAlign: 'center' },
  headerH1: { color: '#212529', margin: '0 0 5px 0', fontSize: '1.8em' },
  headerP: { margin: 0, fontSize: '0.9em', color: '#666' },
  section: { marginBottom: '15px', padding: '15px', backgroundColor: '#ffffff', borderRadius: '6px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' },
  sectionHeading: { marginTop: '0', marginBottom: '12px', color: '#343a40', borderBottom: '1px solid #e9ecef', paddingBottom: '6px', fontSize: '1.2em' },
  form: { display: 'flex', flexDirection: 'column', gap: '10px' },
  inputGroup: { display: 'flex', flexDirection: 'column' },
  label: { marginBottom: '3px', fontWeight: 'bold', fontSize: '0.85em', color: '#495057' },
  input: { padding: '8px 10px', border: '1px solid #ced4da', borderRadius: '4px', fontSize: '0.95em', backgroundColor: '#fff' },
  textarea: { padding: '8px 10px', border: '1px solid #ced4da', borderRadius: '4px', fontSize: '0.95em', minHeight: '50px', resize: 'vertical', backgroundColor: '#fff' },
  button: { padding: '8px 12px', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '0.9em', fontWeight: 'bold', transition: 'background-color 0.2s ease' },
  primaryButton: { backgroundColor: '#007aff', color: 'white' },
  secondaryButton: { backgroundColor: '#6c757d', color: 'white' },
  dangerButton: { backgroundColor: '#dc3545', color: 'white' },
  buttonList: { listStyle: 'none', padding: '0' },
  buttonListItem: { backgroundColor: '#fff', padding: '8px 12px', border: '1px solid #e9ecef', borderRadius: '5px', marginBottom: '6px', display: 'flex', flexDirection: 'column', gap: '4px' },
  buttonListItemHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  buttonLabelContainer: { display: 'flex', alignItems: 'center', gap: '10px' },
  colorSwatch: { width: '15px', height: '15px', borderRadius: '3px', border: '1px solid #ccc', flexShrink: 0 },
  buttonLabel: { fontWeight: 'bold', fontSize: '1.05em', color: '#007aff' },
  buttonActions: { display: 'flex', gap: '8px' },
  buttonDetails: { fontSize: '0.8em', color: '#495057', wordBreak: 'break-all', paddingLeft: '25px' },
  code: { fontFamily: 'monospace', backgroundColor: '#e9ecef', color: '#212529', padding: '2px 4px', borderRadius: '3px', fontSize: '0.9em' },
  variableDisplay: { marginTop: '4px', paddingLeft: '25px' },
  variableTag: { display: 'inline-block', backgroundColor: '#e9ecef', color: '#333', padding: '2px 6px', borderRadius: '4px', marginRight: '6px', marginBottom: '6px', fontSize: '0.8em' },
  modalOverlay: { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0, 0, 0, 0.6)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 },
  modalContent: { backgroundColor: 'white', padding: '20px', borderRadius: '8px', boxShadow: '0 5px 15px rgba(0,0,0,0.3)', width: '90%', maxWidth: '550px' },
  modalActions: { display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '15px' },
  flagLegend: { marginTop: '15px', padding: '8px 12px', border: '1px solid #e9ecef', borderRadius: '6px', backgroundColor: '#f8f9fa' },
  flagLegendTitle: { margin: '0 0 8px 0', fontSize: '0.8em', fontWeight: 'bold', color: '#495057' },
  flagLegendGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: '4px 12px', padding: '0', margin: '0' },
  flagLegendItem: { listStyle: 'none', marginBottom: '2px', fontSize: '0.75em', display: 'flex', alignItems: 'center', gap: '5px' },
  noButtonsMessage: { textAlign: 'center', color: '#6c757d', padding: '20px', fontSize: '1.1em' },
  errorMessage: { textAlign: 'center', color: '#721c24', backgroundColor: '#f8d7da', padding: '15px', borderRadius: '4px', border: '1px solid #f5c6cb', marginBottom: '20px' },
  variableEditorGrid: { display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '8px 10px', alignItems: 'center'},
};

const FlagLegend: React.FC = () => (
  <div style={styles.flagLegend}>
    <h4 style={styles.flagLegendTitle}>Function Flags</h4>
    <div style={styles.flagLegendGrid}>
      <li style={styles.flagLegendItem}><code>@</code><span>Device</span></li>
      <li style={styles.flagLegendItem}><code>~</code><span>Monitor</span></li>
      <li style={styles.flagLegendItem}><code>*</code><span>Record</span></li>
      <li style={styles.flagLegendItem}><code>?</code><span>Keyword Mon</span></li>
      <li style={styles.flagLegendItem}><code>#</code><span>Numeric</span></li>
      <li style={styles.flagLegendItem}><code>V</code><span>Variables</span></li>
      <li style={styles.flagLegendItem}><code>T</code><span>Top (Sticky)</span></li>
      <li style={styles.flagLegendItem}><code>N</code><span>New Window</span></li>
      <li style={styles.flagLegendItem}><code>K</code><span>Keep Local</span></li>
      <li style={styles.flagLegendItem}><code>M</code><span>Mobile SSH</span></li>
      <li style={styles.flagLegendItem}><code>{'&'}</code><span>Background</span></li>
      <li style={styles.flagLegendItem}><code>{'>'}</code><span>Confirm</span></li>
    </div>
    <h4 style={{...styles.flagLegendTitle, marginTop: '10px'}}>Modifier Flags</h4>
    <div style={styles.flagLegendGrid}>
       <li style={styles.flagLegendItem}><code>1-99</code><span>Font Size</span></li>
       <li style={styles.flagLegendItem}><code>D</code><span>Dim Color</span></li>
    </div>
    <h4 style={{...styles.flagLegendTitle, marginTop: '10px'}}>Color Flags</h4>
    <div style={styles.flagLegendGrid}>
      {Object.entries(BASE_COLORS).map(([code, hex]) => (
        <li key={code} style={styles.flagLegendItem}>
          <span style={{ ...styles.colorSwatch, backgroundColor: hex }}></span>
          <code>{code}</code>
        </li>
      ))}
       <li style={styles.flagLegendItem}><span style={{ ...styles.colorSwatch, backgroundColor: '#000000' }}></span><span>(Default)</span></li>
    </div>
  </div>
);

const VariableDisplay: React.FC<{ button: ButtonConfig; sessionVars: SessionVars, inModal?: boolean }> = ({ button, sessionVars, inModal = false }) => {
  const varRegex = /\{\{([^:}]+):?([^}]*)?\}\}/g;
  const variables = [];
  let match;
  while ((match = varRegex.exec(button.command)) !== null) {
    const varName = match[1];
    const currentValue = sessionVars[varName];
    if (varName && currentValue !== undefined) { variables.push({ name: varName, value: currentValue }); }
  }

  if (variables.length === 0) { return null; }
  return (
    <div style={inModal ? { ...styles.variableDisplay, paddingLeft: 0, marginTop: '10px', borderTop: '1px solid #eee', paddingTop: '10px' } : styles.variableDisplay}>
      {variables.map(v => (
        <span key={v.name} style={styles.variableTag}><code style={{fontWeight: 'bold'}}>{v.name}</code> = <code>{v.value}</code></span>
      ))}
    </div>
  );
};

const SessionVariables: React.FC<{ sessionVars: SessionVars; onSave: (vars: SessionVars) => Promise<void> }> = ({ sessionVars, onSave }) => {
  const [editedVars, setEditedVars] = useState<SessionVars>(sessionVars);

  useEffect(() => {
    setEditedVars(sessionVars);
  }, [sessionVars]);

  const handleSave = () => {
    onSave(editedVars);
  };

  const sortedVarKeys = Object.keys(editedVars).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  return (
    <section style={styles.section}>
      <h2 style={styles.sectionHeading}>Session Variables</h2>
      {sortedVarKeys.length > 0 ? (
        <form onSubmit={(e) => { e.preventDefault(); handleSave(); }}>
          <div style={styles.variableEditorGrid}>
            {sortedVarKeys.map((key) => (
              <React.Fragment key={key}>
                <label htmlFor={`var-${key}`} style={styles.label}>{key}:</label>
                <input
                  id={`var-${key}`}
                  type="text"
                  value={editedVars[key]}
                  onChange={(e) => setEditedVars({ ...editedVars, [key]: e.target.value })}
                  style={styles.input}
                />
              </React.Fragment>
            ))}
          </div>
          <button type="submit" style={{ ...styles.button, ...styles.primaryButton, marginTop: '15px' }}>Save Variables</button>
        </form>
      ) : <p style={styles.noButtonsMessage}>No session variables found.</p>}
    </section>
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

  const fetchAllData = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/buttons`);
      if (!response.ok) throw new Error(`Failed to connect to driver. Is it running? (Status: ${response.status})`);
      const data = await response.json();
      setButtons(data.buttons); setSessionVars(data.variables); setApiError(null);
    } catch (error) { console.error("Error fetching data:", error); setApiError(String(error)); }
  };

  useEffect(() => {
    fetchAllData();
  }, []);

  const handleAddButton = async (e: FormEvent) => {
    e.preventDefault();
    if (!newLabel.trim()) { alert('Label is required.'); return; }
    const newButtonData = { label: newLabel, command: newCommand, flags: newFlags, monitor_keyword: newMonitorKeyword };
    try {
      const response = await fetch(`${API_BASE_URL}/api/buttons`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newButtonData) });
      if (!response.ok) throw new Error('Failed to add button.');
      fetchAllData();
      setNewLabel(''); setNewCommand(''); setNewFlags(''); setNewMonitorKeyword('');
    } catch (error) { console.error("Error adding button:", error); alert("Error: Could not add the button."); }
  };

  const handleDeleteButton = async (id: number) => {
    if (window.confirm('Are you sure you want to delete this button configuration?')) {
      try {
        const response = await fetch(`${API_BASE_URL}/api/buttons/${id}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete button.');
        fetchAllData();
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
      fetchAllData();
      closeEditModal();
    } catch (error) { console.error("Error saving button:", error); alert("Error: Could not save changes."); }
  };
  
  const handleSaveVariables = async (vars: SessionVars) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/variables`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(vars) });
      if (!response.ok) throw new Error('Failed to save variables.');
      fetchAllData();
      alert('Variables saved successfully!');
    } catch (error) { console.error("Error saving variables:", error); alert("Error: Could not save variables."); }
  };

  const openEditModal = (button: ButtonConfig) => {
    setEditingButton(button); setEditLabel(button.label); setEditCommand(button.command);
    setEditFlags(button.flags); setEditMonitorKeyword(button.monitor_keyword || ''); setIsEditModalOpen(true);
  };
  const closeEditModal = () => { setIsEditModalOpen(false); setEditingButton(null); };

  return (
    <div style={styles.container}>
      <header style={{...styles.header, paddingTop: '10px' }}><h1>StreamDeck Live Controller</h1><p style={styles.headerP}>Manage button configurations for your running StreamDeck driver.</p></header>
      {apiError && <div style={styles.errorMessage} role="alert"><strong>Connection Error:</strong> {apiError}</div>}
      
      <SessionVariables sessionVars={sessionVars} onSave={handleSaveVariables} />

      <section style={styles.section}>
        <h2>Add New Button</h2>
        <form onSubmit={handleAddButton} style={styles.form}>
          <div style={styles.inputGroup}><label htmlFor="newLabel" style={styles.label}>Label:</label><input id="newLabel" type="text" value={newLabel} onChange={e => setNewLabel(e.target.value)} style={styles.input} required /></div>
          <div style={styles.inputGroup}><label htmlFor="newCommand" style={styles.label}>Command:</label><textarea id="newCommand" value={newCommand} onChange={e => setNewCommand(e.target.value)} style={styles.textarea} rows={2} /></div>
          <div style={styles.inputGroup}><label htmlFor="newFlags" style={styles.label}>Flags:</label><input id="newFlags" type="text" value={newFlags} onChange={e => setNewFlags(e.target.value)} style={styles.input} placeholder="e.g., R16@~, GD#N, B12VT" /></div>
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
                  <p style={{margin: '2px 0'}}><strong>Command:</strong> <code style={styles.code}>{button.command || '(empty)'}</code></p>
                  <p style={{margin: '2px 0'}}><strong>Flags:</strong> <code style={styles.code}>{button.flags || '(none)'}</code></p>
                  {button.monitor_keyword && <p style={{margin: '2px 0'}}><strong>Monitor:</strong> <code style={styles.code}>{button.monitor_keyword}</code></p>}
                </div>
                <VariableDisplay button={button} sessionVars={sessionVars} />
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
              <div style={styles.inputGroup}><label htmlFor="editCommand" style={styles.label}>Command:</label><textarea id="editCommand" value={editCommand} onChange={e => setEditCommand(e.target.value)} style={styles.textarea} rows={2} /></div>
              <div style={styles.inputGroup}><label htmlFor="editFlags" style={styles.label}>Flags:</label><input id="editFlags" type="text" value={editFlags} onChange={e => setEditFlags(e.target.value)} style={styles.input} /></div>
              <div style={styles.inputGroup}><label htmlFor="editMonitorKeyword" style={styles.label}>Monitor Keyword:</label><input id="editMonitorKeyword" type="text" value={editMonitorKeyword} onChange={e => setEditMonitorKeyword(e.target.value)} style={styles.input} /></div>
              <VariableDisplay button={editingButton} sessionVars={sessionVars} inModal={true} />
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