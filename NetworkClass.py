# -*- coding: utf-8 -*-
"""
Network Model:
Liquid state machine as described in "Real-Time Computing Without Stable States: A New Framework for Neural Computation Based on Perturbations"
Maass, Wolfgang, Natschlager and Markram, 2002.

Models:
Integrate and fire(LIF):
Leaky integrate and fire model (Gerstner, 2014)

Adaptation (SFA):
Spike Frequency Adaptation LIF model (Fuhrmann and Tsodyks, 2002)

LFP calculation:
LFPy: a tool for biophysical simulation of extracellular potentials generated by detailed model neurons (Linden et al. 2013)

@author: yaron
"""

import numpy as np

from matplotlib import pyplot as plt
import plotly.graph_objs as go
import plotly as py
import plotly.express as px
from scipy.stats import norm
import time



class Network:

    def __init__(self, model='LIF', dim=(15, 3, 3), Vreset=5, inh_frac=0.2, R=1, tau=30, Vr=0, Vth=15, lamb=2,
                 ref=(2, 3),lamb_in=2,tau_psc=(6, 3), keep_data=1, dt=0.01, tauRise=1, tauDec=6.5, Vk=-60.6, gk=10,
                 alpha=0.02, tauN=230, J=0.0615, input_num=1, clusters=1, cluster_pr=0.1,
                 V_syn={(1, 1): 5, (1, 0): 25, (0, 1): -20, (0, 0): -20},connect_const={(1, 1): 0.3, (1, 0): 0.2, (0, 1): 0.4,(0, 0): 0.1}):
        """
        Initialize network
            model - Neurons spiking model
            dim - Dimension of the network (3d)
            inh_frac - Fraction of inhibitory neurons
            R - resistance (G Omega)
            tau - Membrane time constant (ms)
            Vr - Resting potential (mV)
            Vth - Spiking threshold (mV)
            Vreset - Potential decrease after spike (mV)
            ref - Refractory periods (I,E) (ms)
            dt - Simulations time step (ms)
            tau_psc - Post synaptic current decay (I,E) (ms)

            keep_data - keep data of simulations (bool)
            lamb - Connections distribution parameter
            clusters - Number of clusters. number of neurons will be multiplied bu cluster num
            cluster_pr - The probability of connection between two neurons in different clusters


            // SFA parameters
            Vk - K+ reversal potential (mV)
            gk - K+ maximal conductance ((G Omega)^-1)
            alpha - Step increase in n
            tauN - Time of deactivation of adaptation current
            J - Synaptic strength (pA)
            tauRise - Synaptic rise time constant (ms)
            tauDec - Synaptic decay time constant (ms)
            Vsyn - Synaptic reversal potential (mV)
        """

        self.Vth = Vth
        self.Vr = Vr
        self.Vreset = Vth - Vreset  # Reset potential (mV)
        self.R = R
        self.tau = tau
        self.dt = dt
        self.t = 0  # Current time
        self.dim = np.array(dim)
        self.clusters = clusters
        if clusters > 1:
            self.dim[1] = dim[1] * clusters
        self.neuron_num = np.prod(self.dim)
        self.cluster_pr = cluster_pr
        self.w = 1  # Synaptic weights
        self.ref = np.array(ref)
        self.input_num = input_num
        self.input_t = np.full(self.input_num, -1, dtype=float)
        self.input_t_syn = np.zeros(self.input_num)
        self.connect_const = connect_const  # Connections distribution parameter (EE,EI,IE,II)


        self.lamb_in = lamb_in
        self.connections = np.zeros([self.neuron_num, self.neuron_num])
        self.input_connections = np.zeros([self.neuron_num, self.input_num])
        self.tau_psc = np.array(tau_psc)
        self.lamb = lamb
        self.keep_data = keep_data
        self.model_type = model

        if model == 'SFA':
            self.model = self.SFA
            self.synaptic_current = self.synaptic_current_SFA
            self.input_current = self.input_current_SFA

        if model == 'LIF' or model == 'SOC':
            self.model = self.LIF
            self.synaptic_current = self.synaptic_current_LIF
            self.input_current = self.input_current_LIF
        self.fig = None
        # Choose inhibitory neurons and generate connections
        self.inh_idx = np.sort(
            np.random.choice(self.neuron_num, size=np.int(self.neuron_num * inh_frac), replace=False))

        self.type_array = np.ones(self.neuron_num, dtype=int)
        self.type_array[self.inh_idx] = 0
        self.V_syn = V_syn

        self.generate_connections()

        self.connections_bool = self.connections != 0
        self.in_connections_bool = self.input_connections != 0

        # SFA parameters
        self.Vk = Vk
        self.gk = gk
        self.alpha = alpha
        self.tauN = tauN
        self.J = J
        self.tauRise = tauRise
        self.tauDec = tauDec

        self.reset_history()

    def reset_history(self):
        """
        Reset network data
        """
        if self.model_type == 'SOC_syn':
            self.activity_size = self.neuron_num + self.input_num
            self.active_syn = np.zeros(self.activity_size, dtype=int)
        else:
            self.activity_size = self.neuron_num

        self.spikes = np.zeros(self.neuron_num, dtype=int)  # Current spiking neurons
        self.spikes_in = np.zeros(self.input_num, dtype=int)  # Current spiking neurons
        self.spikes_syn = np.zeros(self.activity_size, dtype=int)
        self.spikes_t = np.full(self.neuron_num, -1, dtype=float)  # Neurons last spike
        self.spikes_t_syn = np.full(self.neuron_num, -1, dtype=float)  # Neurons last spike synapse
        self.Vs = np.full(self.neuron_num, self.Vr, dtype=float)  # Current potentials
        self.Is = np.zeros(self.neuron_num)  # Current currents
        self.EPSC = np.zeros(self.neuron_num)  # Current post synaptic currents
        self.n = np.zeros(self.neuron_num)  # Current fraction of open conductance
        self.Ia = np.zeros(self.neuron_num)  # Current adaptation current (nA)
        self.type_array[self.inh_idx] = 0  # TODO
        self.active = np.zeros(self.activity_size, dtype=int)
        self.A = np.zeros(self.activity_size)
        self.isi = []

    def LIF(self):
        """
        Caluclate LIF derivative:
        """

        return (self.Vr - self.Vs[self.active] + self.Is[self.active] * self.R) / self.tau


    def synaptic_current_LIF(self):
        """
        Calculate LIF post synaptic currents
        """

        dt = self.t - self.spikes_t
        Isyn = np.exp(-dt / self.tau_psc[self.type_array]) * np.heaviside(dt, 1)
        Isyn[self.spikes_t < 0] = 0

        return Isyn

    def input_current_LIF(self):
        """
        Calculate LIF input synaptic currents
        """

        dt = self.t - self.input_t
        Isyn = np.exp(-dt / self.tau_psc[0]) * np.heaviside(dt, 1)
        Isyn[self.input_t < 0] = 0

        return Isyn

    def K_frac(self):
        """
        Calculate fraction of open conductance (SFA)
        """

        time = np.logical_and(self.t - self.spikes_t <= 1, self.spikes_t > 0) # Yaron =!0
        self.n = self.n - self.dt * ((self.n / self.tauN) - self.alpha * (1 - self.n) * time)

    def SFA(self):
        """
        Calculate SFA derivatives
        """

        self.K_frac()
        self.Ia = self.gk * self.n * (self.Vs - self.Vk)
        self.Ia = self.gk * self.n * (self.Vs - self.Vk)

        return (self.Vr - self.Vs + (self.Is - self.Ia) * self.R) / self.tau



    def synaptic_current_SFA(self):
        """
        Calculate SFA synaptic currents
        """

        dt = self.t - self.spikes_t
        Isyn = self.J * (np.exp(-dt / self.tauDec) - np.exp(-dt / self.tauRise))
        Isyn[self.spikes_t < 0] = 0 #Yaron ==0
        return Isyn

    def input_current_SFA(self):
        """
        Calculate SFA input synaptic currents
        """

        dt = self.t - self.input_t
        Isyn = self.J * (np.exp(-dt / self.tauDec) - np.exp(-dt / self.tauRise))
        Isyn[self.input_t < 0] = 0 #Yaron

        return Isyn


    def run_model(self, I, input_type=0):
        """
        Simulate network
            I - Current injected (#Neurons array)
            input_type - 0: currents, 1:spiketrain
        """

        self.reset_history()
        t = I.shape[0]

        # Save simulation history
        if self.keep_data:
            self.Vseq = np.zeros((self.neuron_num, int(t) + 1))
            self.Vseq[:, 0] = self.Vs
            self.spikes_seq = np.zeros((self.neuron_num, int(t) + 1))
            self.EPSC_seq = np.zeros((self.neuron_num, int(t) + 1))
            self.A_seq = np.zeros((self.activity_size, int(t) + 1))
            self.n_seq = np.zeros((self.neuron_num, int(t) + 1))
            self.I_seq = I

        # Simulate numerically
        for i, t_cur in enumerate(np.linspace(self.dt, t * self.dt, t), start=1):
            self.t = t_cur

            if self.model_type == 'LIF':
                # LIF neurons have refractory period
                self.active = np.nonzero(
                    np.logical_or(self.t - self.spikes_t > self.ref[self.type_array], self.spikes_t == -1))
                active_neurons = self.active

            if self.model_type == 'SFA':
                self.active = np.arange(self.neuron_num, dtype=int)
                active_neurons = self.active

            if input_type:

                self.input_t[np.where(I[i - 1])] = t_cur
                I_cur = self.input_connections.dot(self.input_current())-\
                            (self.in_connections_bool.dot(self.input_current())*self.Vs)
            else:
                I_cur = I[i - 1]

            # Update network

            self.Vs[active_neurons] = self.Vs[active_neurons] + self.dt * self.model()

            self.spikes = self.Vs > self.Vth


            self.spikes_t[self.spikes] = t_cur

            self.Vs[self.spikes] =  0 #Yaron =+40
            if self.model_type == 'SFA':
                self.EPSC = self.connections.dot(self.synaptic_current())-\
                            (self.connections_bool.dot(self.synaptic_current())*self.Vs)  # Adaptation
            else:
                self.EPSC = self.connections.dot(self.synaptic_current())

            if self.keep_data:
                self.Vseq[:, i] = self.Vs
                self.spikes_seq[:, i] = self.spikes
                self.EPSC_seq[:, i] = self.EPSC
                self.A_seq[:, i] = self.A
                self.n_seq[:, i] = self.n
            self.Vs[self.spikes] = self.Vreset

            # Update input currents for next iteration
            self.Is = I_cur + self.EPSC

    def get_pos(self, idx):
        """
        Get a spacial position of an indicated neuron
            idx - index of the neuron
        """
        return np.array(np.unravel_index(idx, self.dim))

    def fire_rate(self,window=1000):
        return np.convolve(x, np.ones(N) / N, mode='valid')

    def generate_connections(self):
        """
        Generate connections in the network as desribed in Mass, 2002.
        """
        mid = self.dim[2] // 2 - 0.5

        for i in np.arange(self.input_num):

            # Centered input
            for j in range(self.neuron_num//self.clusters):
                neurons_dist = np.linalg.norm(self.get_pos(j) - (0, self.dim[2] - mid, mid))
                c = .242

                connect_pr = c * np.exp(-(neurons_dist / (self.lamb_in)) ** 2)

                #if self.clusters>1:
                #    connect_pr = c * np.exp(-(neurons_dist / (self.lamb_in)) ** 2)
                #else:
                #    connect_pr = c

                if np.random.rand() < connect_pr:
                    self.input_connections[j, i] = self.V_syn[(not(np.isin(j, self.inh_idx)),1)]

        for i in range(self.neuron_num):
            for j in range(self.neuron_num):
                if i == j:
                    continue
                # Get euclidean distance

                if i // (self.neuron_num / self.clusters) != j // (self.neuron_num / self.clusters) and self.clusters>1:
                    if i > j:
                        neurons_dist = (np.linalg.norm(self.get_pos(i) - (0,self.dim[1]-mid,mid)) + np.linalg.norm(self.get_pos(j) - (0,mid,mid)))/2
                        # Calc connection probability
                        c = self.cluster_pr
                        connect_pr = c * np.exp(-(neurons_dist / self.lamb) ** 2)
                    else:
                        connect_pr = 0
                else:
                    neurons_dist = np.linalg.norm(self.get_pos(i) - self.get_pos(j))

                    # Calc connection probability
                    types = (not (np.isin(i, self.inh_idx)), not (np.isin(j, self.inh_idx)))
                    c = self.connect_const[(not (np.isin(i, self.inh_idx)), not (np.isin(j, self.inh_idx)))]
                    connect_pr = c * np.exp(-(neurons_dist / self.lamb) ** 2)

                #if self.model_type == 'SFA':
                #    connect_pr = .242

                if np.random.rand() < connect_pr:
                    self.connections[i][j] = self.V_syn[(not(np.isin(i, self.inh_idx)), not(np.isin(j, self.inh_idx)))]
                if i == j:
                    self.connections[i][j] = 0

    def plot_network(self):
        """
        Visualize network structure

        """
        net_grid = np.mgrid[:self.dim[0], :self.dim[1], :self.dim[2]]
        groups = self.type_array

        # Neurons
        trace1 = go.Scatter3d(x=net_grid[0].ravel(), y=net_grid[1].ravel(), z=net_grid[2].ravel(), mode='markers',
                              name='Neurons',
                              marker=dict(symbol='circle', size=6, color=groups, colorscale=py.colors.qualitative.T10,
                                          line=dict(color='rgb(50,50,50)', width=80)), hoverinfo='text')

        # Synapses

        xe = []
        ye = []
        ze = []

        for i in np.array(np.where(self.connections)).T:
            [ed1, ed2] = self.get_pos(i).T

            xe += [ed1[0], ed2[0], None]
            ye += [ed1[1], ed2[1], None]
            ze += [ed1[2], ed2[2], None]

        trace2 = go.Scatter3d(x=np.ravel(xe), y=np.ravel(ye), z=np.ravel(ze), mode='lines', name='Synapse',
                              line=dict(color='rgb(125,125,125)', width=1), hoverinfo='none')

        # Show in browser
        fig = go.Figure(data=[trace2, trace1])
        fig.show(renderer='browser')

    def plot_spikes(self, window=(0, 0)):
        """
        Plot spiking activity of simulation
            window - Time window for plot

        """
        self.fig = plt.figure()
        self.fig.set_facecolor('xkcd:white')
        if not (np.any(window)):
            t1 = 0
            tn = int(self.t)
        else:
            [t1, tn] = window

        [plt.scatter(np.nonzero(i)[0] * self.dt, np.full(np.nonzero(i)[0].shape[0], j), color='k', s=2) for j, i in
         enumerate(self.spikes_seq)]
        plt.xlabel('Time (ms)')
        plt.xlim(t1 - 1, tn + 1)
        plt.yticks
        plt.ylabel('Neuron')
        #plt.show()

    def plot_spikes3d(self, window=(0, 0)):
        """
        Plot spiking activity of simulation
            window - Time window for plot

        """
        plt.figure()
        if not (np.any(window)):
            t1 = 0
            tn = int(self.t)
        else:
            [t1, tn] = window

        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')


        for j, i in enumerate(self.spikes_seq):
            xs = np.nonzero(i)[0] * self.dt
            [x, y, z] = self.get_pos(j)
            ys = np.full(xs.shape[0],y)
            zs = np.full(xs.shape[0], z)
            ax.scatter(xs, ys, zs, color='k',s=2)

        ax.set_xlabel('Time (ms)')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')
        #ax.set_xlim(t1 - 1, tn + 1)
        #plt.show()
    def plot_neuron(self, pos=-1, what=[0], window=(0, 0)):
        """
        Plot given neurons activity (seperately)

            pos - Neurons indices for plot. Default -1 plot a random neuron.
            what - Plot V (0) spikes (1) ISI (2) A (3)

        """

        if not (np.any(window)):
            t1 = 0
            tn = int(self.t)
        else:
            [t1, tn] = window

        if pos == -1:
            pos = np.random.randint(self.neuron_num)

        if np.isin(0, what):
            plt.figure()

            plt.plot(np.linspace(0, self.t, int(self.t / self.dt) + 1), self.Vseq[pos, :])
            plt.xlabel('Time (ms)')
            plt.ylabel('V (mV)')
            plt.xlim(t1 - 1, tn + 1)
            plt.show()

        if np.isin(1, what):
            plt.figure()
            plt.scatter(np.linspace(0, self.t, int(self.t / self.dt) + 1), self.spikes_seq[pos, :])
            plt.xlabel('Time (ms)')
            plt.ylabel('Spikes')
            plt.xlim(t1 - 1, tn + 1)
            plt.show()

        if np.isin(2, what):
            plt.figure()
            spike_times = np.where(self.spikes_seq[pos, int(t1 / self.dt):int(tn / self.dt)])[0]
            self.isi = np.array(
                [(spike_times[i + 1] - spike_times[i]) * self.dt for i in range(spike_times.shape[0] - 1)])
            plt.plot(range(self.isi.shape[0]), self.isi)
            # plt.xlim(t1 - 1, tn + 1)
            plt.xlabel('# spike')
            plt.ylabel('Interspike interval (ms)')
            plt.show()

        if np.isin(3, what):
            plt.figure()
            plt.plot(np.linspace(0, self.t, int(self.t / self.dt) + 1), self.A_seq[pos, :])
            plt.xlabel('Time (ms)')
            plt.ylabel('A')
            plt.xlim(t1 - 1, tn + 1)
            plt.show()

    def generate_spiketrain(self,t,dt,f,input_num,plot_bool=False):

        # input_num - number of spikes trains

        spike_train = np.random.rand( int(t/dt),input_num) < f*dt
        if plot_bool:
            plot_spike_train(spike_train)
        return(spike_train)

    # LFP functions
    @staticmethod
    def get_r(x, y):
        return np.array([np.sqrt(x ** 2 + y ** 2).flatten(), np.arctan2(y, x).flatten(), np.zeros(x.size)])

    @staticmethod
    def calc_dist(r1, r2):
        # calc distance between polar coordinates r1,r2 using law of cosines
        return np.sqrt(r1[0] ** 2 + r2[0] ** 2 - r1[0] * r2[0] * np.cos(r1[1] - r2[1]))

    def get_phi(self,SPC, r, t, sigma, dim):
        phi = 0
        for i, channel in enumerate(SPC):
            z, x, y = self.get_pos(i)
            r0 = self.get_r(x, y)
            if np.any(r != r0):
                dist = self.calc_dist(r, r0)
                phi += channel[t] / (dist * (4 * np.pi * sigma))
        return phi / (SPC.shape[0] - 1)




